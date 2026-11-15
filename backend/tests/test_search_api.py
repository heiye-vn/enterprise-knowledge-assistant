from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session
from test_import_api import import_environment as import_environment
from test_import_api import upload
from test_indexing_jobs import finish
from test_indexing_jobs import indexed_environment as indexed_environment

from app.model_clients import ModelClient, ModelProblem, RankedItem, Ranking
from app.models import Document

pytestmark = pytest.mark.integration


@pytest.fixture
def searchable(indexed_environment, monkeypatch):
    client, settings, storage = indexed_environment
    original_embed = ModelClient.embed_texts
    monkeypatch.setattr(
        ModelClient,
        "rerank",
        lambda self, question, candidates, top_n: Ranking(
            [RankedItem(i, 1 / (i + 1)) for i in range(min(top_n, len(candidates)))],
            self.settings.qwen_rerank_model,
        ),
    )
    return client, settings, storage, original_embed


def test_only_published_versions_are_searched_and_result_sources_are_fixed(searchable):
    client, settings, *_ = searchable
    old = upload(client, "# 财务\n\n旧制度：报销只需纸质发票。".encode()).json()
    assert finish(client, settings, old["job_id"])["status"] == "ready"
    new = client.post(
        f"/api/documents/{old['document_id']}/versions",
        files={"file": ("new.md", "# 财务\n\n新制度：报销须提供电子发票和审批记录。".encode())},
    ).json()
    assert finish(client, settings, new["job_id"])["status"] == "ready"
    pending = upload(client, "# 待处理\n\n报销假资料".encode()).json()
    response = client.post("/api/search", json={"question": "报销需要什么材料？", "top_k": 5})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"] and {x["job_id"] for x in body["items"]} == {new["job_id"]}
    assert all(
        "纸质" not in x["content"] and x["job_id"] != pending["job_id"] for x in body["items"]
    )
    assert body["snapshot"]["documents"][0]["version_id"] == new["version_id"]
    source = client.get("/api/chunks/" + body["items"][0]["id"]).json()
    assert source["job_id"] == new["job_id"] and source["locators"]


def test_explicit_scope_does_not_expand_to_all_and_empty_scope_is_rejected(searchable):
    client, settings, *_ = searchable
    a = upload(client, "# 财务\n\n报销材料：发票。".encode()).json()
    b = upload(client, "# 人事\n\n请假材料：申请单。".encode()).json()
    finish(client, settings, a["job_id"])
    finish(client, settings, b["job_id"])
    scoped = client.post(
        "/api/search", json={"question": "报销材料", "document_ids": [b["document_id"]]}
    ).json()
    assert {x["document_id"] for x in scoped["items"]} == {b["document_id"]}
    assert (
        client.post("/api/search", json={"question": "问题", "document_ids": []}).status_code == 422
    )
    assert (
        client.post(
            "/api/search", json={"question": "问题", "document_ids": [str(uuid4())]}
        ).status_code
        == 409
    )


def test_deleted_document_is_excluded_and_profile_changes_require_reindex(searchable, test_engine):
    client, settings, *_ = searchable
    accepted = upload(client).json()
    finish(client, settings, accepted["job_id"])
    client.app.state.settings = settings.model_copy(update={"embedding_model": "different-model"})
    response = client.post("/api/search", json={"question": "policy"})
    assert (
        response.status_code == 409 and response.json()["detail"]["code"] == "index_profile_changed"
    )
    client.app.state.settings = settings
    with Session(test_engine) as db, db.begin():
        db.get(Document, UUID(accepted["document_id"])).deleted_at = datetime.now(UTC)
    body = client.post("/api/search", json={"question": "policy"}).json()
    assert body["items"] == [] and body["snapshot"]["documents"] == []


def test_vector_and_rerank_failure_are_explicitly_degraded(searchable, monkeypatch):
    client, settings, *_ = searchable
    accepted = upload(client, "# 报销\n\n发票和审批记录是报销必需材料。".encode()).json()
    finish(client, settings, accepted["job_id"])

    def unavailable(*_a, **_k):
        raise ModelProblem("model_unavailable", "暂不可用", retryable=True)

    monkeypatch.setattr(ModelClient, "embed_texts", unavailable)
    monkeypatch.setattr(ModelClient, "rerank", unavailable)
    response = client.post("/api/search", json={"question": "报销发票"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"] and body["degraded"] and len(body["warnings"]) == 2
    assert client.post("/api/search", json={"question": "火星航天"}).status_code == 503


def test_snapshot_keeps_old_job_if_publication_changes_during_query(searchable, monkeypatch):
    client, settings, _, original_embed = searchable
    first = upload(client, "# 财务\n\n报销旧版原文。".encode()).json()
    finish(client, settings, first["job_id"])
    newer = client.post(
        f"/api/documents/{first['document_id']}/versions",
        files={"file": ("new.md", "# 财务\n\n报销新版原文。".encode())},
    ).json()
    changed = False

    def changing(self, texts, **kwargs):
        nonlocal changed
        if kwargs.get("text_type") == "query" and not changed:
            changed = True
            assert finish(client, settings, newer["job_id"])["status"] == "ready"
        return original_embed(self, texts, **kwargs)

    monkeypatch.setattr(ModelClient, "embed_texts", changing)
    first_search = client.post("/api/search", json={"question": "报销"}).json()
    assert {x["job_id"] for x in first_search["items"]} == {first["job_id"]}
    second_search = client.post("/api/search", json={"question": "报销"}).json()
    assert {x["job_id"] for x in second_search["items"]} == {newer["job_id"]}


def test_invalid_rerank_response_falls_back_with_warning(searchable, monkeypatch):
    client, settings, *_ = searchable
    item = upload(client, "# 报销\n\n发票是报销材料。".encode()).json()
    finish(client, settings, item["job_id"])
    monkeypatch.setattr(
        ModelClient, "rerank", lambda self, *a, **k: Ranking([], self.settings.qwen_rerank_model)
    )
    response = client.post("/api/search", json={"question": "报销发票"})
    assert response.status_code == 200
    assert response.json()["items"] and response.json()["degraded"]
    assert response.json()["warnings"][0]["code"] == "rerank_invalid_model_response"


def test_trace_keeps_scores_and_rank_changes_for_all_fused_candidates(searchable, monkeypatch):
    client, settings, *_ = searchable
    for number in range(3):
        accepted = upload(client, f"# 报销{number}\n\n报销发票材料条款{number}。".encode()).json()
        assert finish(client, settings, accepted["job_id"])["status"] == "ready"
    monkeypatch.setattr(
        ModelClient,
        "rerank",
        lambda self, query, documents, top_n: Ranking(
            [RankedItem(i, score) for i, score in [(2, 0.9), (1, 0.8), (0, 0.7)]],
            self.settings.qwen_rerank_model,
        ),
    )
    body = client.post("/api/search", json={"question": "报销发票", "top_k": 2}).json()
    trace = body["trace"]
    assert len(trace["candidates"]) == 3
    assert sum(c["selected"] for c in trace["candidates"]) == 2
    by_id = {c["source"]["id"]: c for c in trace["candidates"]}
    first = by_id[body["items"][0]["id"]]
    assert first["ranks"]["fusion"] == 3 and first["ranks"]["rerank"] == 1
    assert first["scores"]["bm25"] is not None and first["scores"]["vector_distance"] is not None
    assert first["scores"]["rerank"] == 0.9
    assert all(c["scores"]["rerank"] is not None for c in trace["candidates"])
    assert all(s["duration_ms"] >= 0 for s in trace["stages"] if s["status"] == "completed")


def test_failed_search_stages_have_no_fabricated_scores(searchable, monkeypatch):
    client, settings, *_ = searchable
    accepted = upload(client, "# 报销\n\n报销要提供发票。".encode()).json()
    finish(client, settings, accepted["job_id"])

    def unavailable(*args, **kwargs):
        raise ModelProblem("model_unavailable", "暂不可用", retryable=True)

    monkeypatch.setattr(ModelClient, "embed_texts", unavailable)
    monkeypatch.setattr(ModelClient, "rerank", unavailable)
    trace = client.post("/api/search", json={"question": "报销发票"}).json()["trace"]
    stages = {s["key"]: s for s in trace["stages"]}
    assert stages["vector"]["status"] == stages["rerank"]["status"] == "failed"
    assert all(
        c["scores"]["vector_distance"] is None and c["scores"]["rerank"] is None
        for c in trace["candidates"]
    )
    assert all(c["ranks"]["rerank"] is None for c in trace["candidates"])


def test_empty_library_has_skipped_retrieval_stages(searchable):
    client, *_ = searchable
    trace = client.post("/api/search", json={"question": "报销发票"}).json()["trace"]
    assert trace["candidates"] == []
    assert all(
        stage["status"] == "skipped" and stage["duration_ms"] is None for stage in trace["stages"]
    )
