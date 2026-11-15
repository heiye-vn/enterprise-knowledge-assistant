from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_import_api import import_environment as import_environment
from test_import_api import upload

from app.model_clients import EmbeddingBatch, ModelClient, ModelProblem
from app.models import Chunk, Document, DocumentContent, DocumentVersion, ProcessingJob
from app.tasks.documents import process_document

pytestmark = pytest.mark.integration


@pytest.fixture
def indexed_environment(import_environment, monkeypatch):
    client, settings, storage = import_environment
    settings = settings.model_copy(
        update={
            "embedding_model": "test-embedding",
            "embedding_dimension": 3,
            "embedding_batch_size": 2,
        }
    )
    client.app.state.settings = settings

    def embed(self, texts, **_):
        return EmbeddingBatch([[1.0, 0.5, 0.2] for _ in texts], self.settings.embedding_model)

    monkeypatch.setattr(ModelClient, "embed_texts", embed)
    return client, settings, storage


def job_state(client, identity):
    return client.get(f"/api/processing-jobs/{identity}").json()


def finish(client, settings, identity):
    for _ in range(30):
        process_document(str(identity), settings)
        state = job_state(client, identity)
        if state["status"] not in {"queued", "running"}:
            return state
    pytest.fail("index did not finish")


def test_complete_index_is_published_and_sources_are_fixed_to_job(indexed_environment, test_engine):
    client, settings, _ = indexed_environment
    accepted = upload(client, "# 费用制度\n\n报销必须提交发票和审批记录。".encode()).json()
    state = finish(client, settings, accepted["job_id"])
    assert state["status"] == "ready" and state["stage"] == "done", state
    summary = client.get("/api/documents/" + accepted["document_id"]).json()
    assert summary["can_query"] and summary["status"] == "ready"
    with Session(test_engine) as db:
        assert db.get(Document, UUID(accepted["document_id"])).current_version_id == UUID(
            accepted["version_id"]
        )
        assert db.get(DocumentVersion, UUID(accepted["version_id"])).active_import_job_id == UUID(
            accepted["job_id"]
        )
        chunks = list(db.scalars(select(Chunk).where(Chunk.job_id == UUID(accepted["job_id"]))))
        assert len(chunks) == 1 and len(chunks[0].embedding) == 3
        identity = str(chunks[0].id)
    source = client.get("/api/chunks/" + identity)
    assert source.status_code == 200, source.text
    assert source.json()["job_id"] == accepted["job_id"]
    assert "发票" in source.json()["content"] and "embedding" not in source.json()
    assert (
        client.get(f"/api/document-versions/{accepted['version_id']}/chunks").json()["items"][0][
            "id"
        ]
        == identity
    )


def test_embedding_resume_skips_saved_batches_and_normal_continuations_keep_attempt_count(
    indexed_environment, test_engine, monkeypatch
):
    client, settings, _ = indexed_environment
    accepted = upload(
        client, ("\n".join(f"## 条款{i}\n\n第{i}条审批规定。\n" for i in range(5))).encode()
    ).json()
    calls = []

    def embed(self, texts, **_):
        calls.append(list(texts))
        if len(calls) == 2:
            raise ModelProblem("model_unavailable", "模型暂不可用", retryable=True)
        return EmbeddingBatch([[1.0, 0.2, 0.1] for _ in texts], self.settings.embedding_model)

    monkeypatch.setattr(ModelClient, "embed_texts", embed)
    process_document(accepted["job_id"], settings)
    assert job_state(client, accepted["job_id"])["status"] == "queued"
    process_document(accepted["job_id"], settings)
    assert job_state(client, accepted["job_id"])["error"]["retryable"]
    with Session(test_engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(Chunk)
                .where(Chunk.job_id == UUID(accepted["job_id"]), Chunk.embedding.is_not(None))
            )
            == 2
        )
    assert client.post(f"/api/processing-jobs/{accepted['job_id']}/retry").status_code == 200
    state = finish(client, settings, accepted["job_id"])
    assert state["status"] == "ready" and state["attempt_no"] == 2
    assert calls[0] not in calls[1:] and calls[1] == calls[2]
    assert len(calls) == 4


def test_invalid_dimension_never_publishes_a_partial_index(indexed_environment, monkeypatch):
    client, settings, _ = indexed_environment
    accepted = upload(client).json()
    monkeypatch.setattr(
        ModelClient, "embed_texts", lambda *_a, **_k: EmbeddingBatch([[1, 2]], "test-embedding")
    )
    state = finish(client, settings, accepted["job_id"])
    assert state["status"] == "failed" and state["error"]["code"] == "invalid_embedding_batch"
    assert not client.get("/api/documents/" + accepted["document_id"]).json()["can_query"]


def test_reindex_reuses_parsed_content_and_failure_keeps_previous_index(
    indexed_environment, test_engine, monkeypatch
):
    client, settings, _ = indexed_environment
    accepted = upload(client).json()
    assert finish(client, settings, accepted["job_id"])["status"] == "ready"
    identity = str(uuid4())
    path = f"/api/document-versions/{accepted['version_id']}/reindex"
    response = client.post(path, json={"job_id": identity})
    assert response.status_code == 202, response.text
    assert client.post(path, json={"job_id": identity}).json() == response.json()
    monkeypatch.setattr(
        "app.tasks.documents.parse_markdown", lambda *_: pytest.fail("must reuse parsed result")
    )

    def unavailable(*_a, **_k):
        raise ModelProblem("model_unavailable", "暂不可用", retryable=True)

    monkeypatch.setattr(ModelClient, "embed_texts", unavailable)
    state = finish(client, settings, identity)
    assert state["status"] == "failed"
    with Session(test_engine) as db:
        assert db.get(DocumentVersion, UUID(accepted["version_id"])).active_import_job_id == UUID(
            accepted["job_id"]
        )
        assert (
            db.get(DocumentContent, UUID(identity)).markdown
            == db.get(DocumentContent, UUID(accepted["job_id"])).markdown
        )
    summary = client.get("/api/documents/" + accepted["document_id"]).json()
    assert summary["can_query"] and summary["latest_processing"]["job_id"] == identity


def test_late_older_version_cannot_reverse_current_version(indexed_environment, test_engine):
    client, settings, _ = indexed_environment
    first = upload(client, b"# old\nOld policy").json()
    assert finish(client, settings, first["job_id"])["status"] == "ready"
    new = client.post(
        f"/api/documents/{first['document_id']}/versions",
        files={"file": ("new.md", b"# new\nNew policy")},
    ).json()
    assert finish(client, settings, new["job_id"])["status"] == "ready"
    with Session(test_engine) as db, db.begin():
        job = db.get(ProcessingJob, UUID(first["job_id"]))
        job.status = "queued"
    assert finish(client, settings, first["job_id"])["status"] == "ready"
    with Session(test_engine) as db:
        assert db.get(Document, UUID(first["document_id"])).current_version_id == UUID(
            new["version_id"]
        )


def test_expired_worker_cannot_save_vectors_or_publish(
    indexed_environment, test_engine, monkeypatch
):
    client, settings, _ = indexed_environment
    accepted = upload(client).json()

    def expire(self, texts, **_):
        with Session(test_engine) as db, db.begin():
            db.get(ProcessingJob, UUID(accepted["job_id"])).lease_expires_at = datetime.now(
                UTC
            ) - timedelta(seconds=1)
        return EmbeddingBatch([[1, 0, 0] for _ in texts], self.settings.embedding_model)

    monkeypatch.setattr(ModelClient, "embed_texts", expire)
    process_document(accepted["job_id"], settings)
    with Session(test_engine) as db:
        assert not db.scalar(
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.job_id == UUID(accepted["job_id"]), Chunk.embedding.is_not(None))
        )
        assert db.get(Document, UUID(accepted["document_id"])).current_version_id is None


def test_retry_old_failure_rejects_another_active_generation(indexed_environment, test_engine):
    client, settings, _ = indexed_environment
    accepted = upload(client).json()
    assert finish(client, settings, accepted["job_id"])["status"] == "ready"
    path = f"/api/document-versions/{accepted['version_id']}/reindex"
    old = str(uuid4())
    assert client.post(path, json={"job_id": old}).status_code == 202
    with Session(test_engine) as db, db.begin():
        job = db.get(ProcessingJob, UUID(old))
        job.status, job.stage = "failed", "embedding"
        job.error = {"code": "model_unavailable", "message": "暂不可用", "retryable": True}
    active = str(uuid4())
    assert client.post(path, json={"job_id": active}).status_code == 202
    response = client.post(f"/api/processing-jobs/{old}/retry")
    assert response.status_code == 409, response.text
    assert job_state(client, old)["status"] == "failed"


def test_late_older_generation_keeps_newer_same_version_publication(
    indexed_environment, test_engine
):
    client, settings, _ = indexed_environment
    first = upload(client).json()
    assert finish(client, settings, first["job_id"])["status"] == "ready"
    newer = str(uuid4())
    assert (
        client.post(
            f"/api/document-versions/{first['version_id']}/reindex", json={"job_id": newer}
        ).status_code
        == 202
    )
    assert finish(client, settings, newer)["status"] == "ready"
    with Session(test_engine) as db, db.begin():
        db.get(ProcessingJob, UUID(first["job_id"])).status = "queued"
    assert finish(client, settings, first["job_id"])["status"] == "ready"
    with Session(test_engine) as db:
        assert db.get(DocumentVersion, UUID(first["version_id"])).active_import_job_id == UUID(
            newer
        )
