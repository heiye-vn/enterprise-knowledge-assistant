import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable
from sqlalchemy import delete
from sqlalchemy.orm import Session
from test_import_api import import_environment as import_environment
from test_import_api import upload
from test_indexing_jobs import finish
from test_indexing_jobs import indexed_environment as indexed_environment

from app.model_clients import ChatReply, ModelClient, ModelProblem
from app.models import Document, ProcessingJob

pytestmark = pytest.mark.integration


@pytest.fixture
def graph_environment(indexed_environment, monkeypatch):
    client, original, storage = indexed_environment
    settings = original.model_copy(
        update={"graph_namespace": "test-graph-" + str(uuid4()), "graph_batch_size": 1}
    )
    client.app.state.settings = settings
    calls = []

    def complete(self, messages, **kwargs):
        assert kwargs["purpose"] == "graph_extract"
        units = json.loads(messages[-1]["content"])["units"]
        calls.extend(unit["unit_id"] for unit in units)
        rules = []
        for unit in units:
            if "考勤制度" in unit["text"]:
                relations = [{"type": "references", "target": "考勤制度"}]
            else:
                relations = [
                    {"type": "approved_by", "target": "直属主管"},
                    {"type": "recorded_by", "target": "人力资源部"},
                ]
            rules.append(
                {
                    "unit_id": unit["unit_id"],
                    "title": "原文规则",
                    "conditions": [unit["text"]],
                    "relations": relations,
                }
            )
        return ChatReply(json.dumps({"rules": rules}, ensure_ascii=False), "qwen", "test")

    monkeypatch.setattr(ModelClient, "complete", complete)
    yield client, settings, calls
    from app.db import create_db_engine

    engine = create_db_engine(settings)
    with Session(engine) as db, db.begin():
        db.execute(
            delete(ProcessingJob).where(
                ProcessingJob.job_type == "graph",
                ProcessingJob.config["namespace"].astext == settings.graph_namespace,
            )
        )
    engine.dispose()
    with GraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password.get_secret_value())
    ) as driver:
        with driver.session() as session:
            session.run(
                "MATCH (n:KnowledgeNode {namespace:$namespace}) DETACH DELETE n",
                namespace=settings.graph_namespace,
            ).consume()


def source_doc(client, settings, text=None, filename="考勤制度.md"):
    response = upload(
        client,
        (
            text
            or "# 请假\n\n超过3个工作日，由直属主管审批，人力资源部仅备案，不替代前述业务审批。"
        ).encode(),
        filename=filename,
    )
    assert response.status_code == 202, response.text
    accepted = response.json()
    assert finish(client, settings, accepted["job_id"])["status"] == "ready"
    return accepted


def run_graph(client, settings, identity):
    from app.tasks.graph import process_graph

    for _ in range(100):
        process_graph(identity, settings)
        state = client.get("/api/processing-jobs/" + identity).json()
        if state.get("status") not in ["queued", "running"]:
            return state
    pytest.fail("graph did not reach a terminal state")


def test_empty_library_and_pending_documents_do_not_generate_fictional_graphs(graph_environment):
    client, settings, _ = graph_environment
    assert client.get("/api/graph").json()["nodes"] == []
    assert client.post("/api/graph/build", json={}).status_code == 409
    upload(client)
    assert client.post("/api/graph/build", json={}).status_code == 409


def test_real_projection_has_evidence_and_build_is_idempotent(graph_environment):
    client, settings, calls = graph_environment
    source = source_doc(client, settings)
    first = client.post("/api/graph/build", json={})
    assert first.status_code == 202, first.text
    job = first.json()["jobs"][0]
    assert client.post("/api/graph/build", json={}).json()["jobs"][0]["id"] == job["id"]
    assert run_graph(client, settings, job["id"])["status"] == "ready"
    body = client.get("/api/graph").json()
    assert body["available"] and body["nodes"] and body["edges"] and body["sources"]
    predicates = {edge["predicate"] for edge in body["edges"]}
    assert {"approved_by", "recorded_by"} <= predicates
    for evidence in body["sources"].values():
        assert evidence["source"]["job_id"] == source["job_id"]
        assert evidence["quote"] in evidence["source"]["content"]
    before = len(calls)
    repeated = client.post("/api/graph/build", json={}).json()
    assert repeated["created"] == 0 and repeated["jobs"][0]["id"] == job["id"]
    assert len(calls) == before
    again = client.get("/api/graph").json()
    assert again["fingerprint"] == body["fingerprint"] and again["edges"] == body["edges"]


def test_projection_failure_retries_saved_facts_without_recalling_model(
    graph_environment, monkeypatch
):
    from app.graph.store import GraphStore

    client, settings, calls = graph_environment
    source_doc(client, settings)
    job = client.post("/api/graph/build", json={}).json()["jobs"][0]
    original = GraphStore.project
    monkeypatch.setattr(
        GraphStore,
        "project",
        lambda *a, **k: (_ for _ in ()).throw(ServiceUnavailable("controlled")),
    )
    state = run_graph(client, settings, job["id"])
    assert state["status"] == "failed" and state["error"]["retryable"]
    before = len(calls)
    monkeypatch.setattr(GraphStore, "project", original)
    retried = client.post("/api/graph/build", json={}).json()["jobs"][0]
    assert retried["id"] == job["id"]
    assert run_graph(client, settings, job["id"])["status"] == "ready"
    assert len(calls) == before
    assert client.get("/api/graph").json()["nodes"]


def test_batch_failure_resumes_after_completed_units(graph_environment, monkeypatch):
    client, settings, calls = graph_environment
    source_doc(
        client,
        settings,
        "# 请假\n\n超过3个工作日，由直属主管审批，人力资源部仅备案。\n\n"
        "## 调休\n\n调休应事前取得直属主管批准，人力资源部备案。",
    )
    real = ModelClient.complete
    count = 0

    def once(self, *args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise ModelProblem("model_unavailable", "受控超时", retryable=True)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(ModelClient, "complete", once)
    job = client.post("/api/graph/build", json={}).json()["jobs"][0]
    assert run_graph(client, settings, job["id"])["status"] == "failed"
    saved = list(calls)
    client.post("/api/graph/build", json={})
    state = run_graph(client, settings, job["id"])
    assert state["status"] == "ready" and state["attempt_no"] == 2
    assert all(calls.count(unit) == 1 for unit in saved)


def test_neo4j_read_failure_is_explicit_and_job_status_stays_available(
    graph_environment, monkeypatch
):
    from app.graph.store import GraphStore

    client, settings, _ = graph_environment
    source_doc(client, settings)
    job = client.post("/api/graph/build", json={}).json()["jobs"][0]
    run_graph(client, settings, job["id"])
    monkeypatch.setattr(
        GraphStore, "read", lambda *a, **k: (_ for _ in ()).throw(ServiceUnavailable("controlled"))
    )
    body = client.get("/api/graph").json()
    assert not body["available"] and body["error"]["code"] == "graph_unavailable"
    assert body["jobs"][0]["status"] == "ready"
    assert client.get("/api/health/live").status_code == 200


def test_deleted_sources_and_changed_imports_do_not_leak_old_graphs(graph_environment, test_engine):
    client, settings, _ = graph_environment
    source = source_doc(client, settings)
    job = client.post("/api/graph/build", json={}).json()["jobs"][0]
    run_graph(client, settings, job["id"])
    assert client.get("/api/graph").json()["nodes"]
    with Session(test_engine) as db, db.begin():
        db.get(Document, UUID(source["document_id"])).deleted_at = datetime.now(UTC)
    assert client.get("/api/graph").json()["nodes"] == []
    assert (
        client.post("/api/graph/build", json={"document_ids": [source["document_id"]]}).status_code
        == 409
    )


def test_catalog_refresh_reuses_extraction_and_links_actual_document(
    graph_environment, monkeypatch
):
    client, settings, calls = graph_environment
    first = source_doc(
        client,
        settings,
        "# 手册\n\n员工请假应按《考勤制度》办理，未经批准不得休假。",
        filename="员工手册.md",
    )
    job = client.post("/api/graph/build", json={}).json()["jobs"][0]
    run_graph(client, settings, job["id"])
    original_calls = list(calls)
    initial_graph = client.get("/api/graph").json()
    referenced = next(node for node in initial_graph["nodes"] if node["title"] == "考勤制度")
    assert referenced["source_available"] is False
    second = source_doc(client, settings)
    jobs = client.post("/api/graph/build", json={}).json()["jobs"]
    for item in jobs:
        assert run_graph(client, settings, item["id"])["status"] == "ready"
    assert all(calls.count(unit) == 1 for unit in original_calls)
    body = client.get("/api/graph").json()
    target_id = "document:" + second["document_id"]
    assert next(node for node in body["nodes"] if node["id"] == target_id)["source_available"]
    assert any(
        edge["predicate"] == "references" and edge["target"] == target_id for edge in body["edges"]
    )
    assert {item["document_id"] for item in body["jobs"]} == {
        first["document_id"],
        second["document_id"],
    }


def test_expired_projection_cannot_be_published(graph_environment, monkeypatch, test_engine):
    from app.graph.store import GraphStore

    client, settings, _ = graph_environment
    source_doc(client, settings)
    job = client.post("/api/graph/build", json={}).json()["jobs"][0]
    original = GraphStore.project

    def expire(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        with Session(test_engine) as db, db.begin():
            record = db.get(ProcessingJob, UUID(job["id"]))
            record.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        return result

    monkeypatch.setattr(GraphStore, "project", expire)
    from app.tasks.graph import process_graph

    for _ in range(10):
        process_graph(job["id"], settings)
    assert not client.get("/api/graph").json()["nodes"]
    with Session(test_engine) as db:
        assert db.get(ProcessingJob, UUID(job["id"])).status != "ready"


def test_all_rejected_results_fail_explicitly_and_can_be_regenerated(
    graph_environment, monkeypatch
):
    client, settings, _ = graph_environment
    source_doc(client, settings)
    original = ModelClient.complete

    def invalid(self, messages, **kwargs):
        unit = json.loads(messages[-1]["content"])["units"][0]
        return ChatReply(
            json.dumps(
                {
                    "rules": [
                        {
                            "unit_id": unit["unit_id"],
                            "title": "无依据规则",
                            "conditions": [unit["text"]],
                            "relations": [{"type": "approved_by", "target": "不存在的审批人"}],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            "qwen",
            "test",
        )

    monkeypatch.setattr(ModelClient, "complete", invalid)
    job = client.post("/api/graph/build", json={}).json()["jobs"][0]
    failed = run_graph(client, settings, job["id"])
    assert failed["status"] == "failed" and failed["error"]["code"] == "graph_all_rejected"
    monkeypatch.setattr(ModelClient, "complete", original)
    assert client.post("/api/graph/build", json={}).json()["jobs"][0]["id"] == job["id"]
    assert run_graph(client, settings, job["id"])["status"] == "ready"
    assert client.get("/api/graph").json()["nodes"]


def test_worker_rejects_changed_model_configuration(graph_environment):
    client, settings, calls = graph_environment
    source_doc(client, settings)
    job = client.post("/api/graph/build", json={}).json()["jobs"][0]
    changed = settings.model_copy(
        update={"qwen_llm_model": "changed-model", "monkey_llm_model": "changed-model"}
    )
    state = run_graph(client, changed, job["id"])
    assert state["status"] == "failed" and state["error"]["code"] == "graph_config_changed"
    assert calls == []


def test_publishing_a_new_import_excludes_the_previous_graph(graph_environment):
    client, settings, _ = graph_environment
    source = source_doc(client, settings)
    job = client.post("/api/graph/build", json={}).json()["jobs"][0]
    assert run_graph(client, settings, job["id"])["status"] == "ready"
    newer = client.post(
        "/api/documents/" + source["document_id"] + "/versions",
        files={
            "file": (
                "new.md",
                "# 请假\n\n新制度：超过3个工作日，由直属主管审批，人力资源部备案。".encode(),
            )
        },
    ).json()
    assert finish(client, settings, newer["job_id"])["status"] == "ready"
    body = client.get("/api/graph").json()
    assert body["nodes"] == [] and body["jobs"][0]["status"] == "not_generated"


@pytest.mark.parametrize(
    "transport,failures,want_ready,want_calls",
    [
        ("connect_error", 1, True, 2),
        ("connect_error", 2, False, 2),
        ("read_timeout", 1, False, 1),
    ],
)
def test_connection_retry_is_bounded_and_never_replays_read_timeout(
    graph_environment,
    monkeypatch,
    transport,
    failures,
    want_ready,
    want_calls,
):
    client, settings, _ = graph_environment
    source_doc(client, settings)
    original = ModelClient.complete
    count = 0

    def interrupted(self, *args, **kwargs):
        nonlocal count
        count += 1
        if count <= failures:
            error = ModelProblem("model_unavailable", "受控网络故障", retryable=True)
            error.transport_code = transport
            raise error
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ModelClient, "complete", interrupted)
    job = client.post("/api/graph/build", json={}).json()["jobs"][0]
    result = run_graph(client, settings, job["id"])
    assert (result["status"] == "ready") is want_ready
    assert count == want_calls
