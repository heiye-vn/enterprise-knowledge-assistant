import hashlib
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session
from test_chat_api import chat_environment as chat_environment
from test_chat_api import grounded as grounded
from test_chat_api import send
from test_import_api import import_environment as import_environment
from test_import_api import upload
from test_indexing_jobs import indexed_environment as indexed_environment

from app.model_clients import ChatReply, ModelClient
from app.models import ProcessingJob
from app.retrieval.search import SearchService

pytestmark = pytest.mark.integration


def test_delete_removes_future_sources_but_keeps_published_history(
    grounded, test_engine, monkeypatch
):
    client, new_session, source, _ = grounded
    monkeypatch.setattr(
        ModelClient,
        "complete",
        lambda *_a, **_k: ChatReply(
            json.dumps(
                {
                    "answerable": True,
                    "answer": "主管、部门负责人和财务经理审批。[1]",
                    "citations": [{"source": 1}],
                }
            ),
            "qwen",
            "test",
        ),
    )
    sid = new_session()
    before = send(client, sid, "6000元谁审批？").json()["assistant"]
    assert before["status"] == "completed" and before["citations"]
    response = client.delete("/api/documents/" + source["document_id"])
    assert response.status_code == 204, response.text
    assert client.delete("/api/documents/" + source["document_id"]).status_code == 204
    assert client.get("/api/documents/" + source["document_id"]).status_code == 404
    assert not client.get("/api/documents").json()["items"]
    settings = client.app.state.settings
    snapshot, sources = SearchService(test_engine, settings).capture(None)
    assert not sources and not snapshot["documents"]
    assert not client.get("/api/graph").json()["jobs"]
    after = client.get("/api/sessions/" + sid).json()["messages"][-1]
    assert after["content"] == before["content"] and after["citations"] == before["citations"]
    parsed = client.get(
        f"/api/document-versions/{source['version_id']}/parsed", params={"job_id": source["job_id"]}
    )
    assert (
        parsed.status_code == 200 and parsed.json()["document_removed"] and parsed.json()["result"]
    )
    chunks = client.get(
        f"/api/document-versions/{source['version_id']}/chunks", params={"job_id": source["job_id"]}
    )
    assert chunks.status_code == 200 and chunks.json()["total"] > 0
    assert client.head(source["file_url"]).status_code == 200
    file = client.get(source["file_url"]).content
    duplicate = client.post(
        "/api/documents/check-duplicate", json={"file_sha256": hashlib.sha256(file).hexdigest()}
    )
    assert duplicate.status_code == 200 and not duplicate.json()["duplicate"]
    assert client.get(f"/api/document-versions/{source['version_id']}/parsed").status_code == 404


def test_delete_blocks_active_jobs_and_deleted_documents_cannot_retry(
    import_environment, test_engine
):
    client, _, _ = import_environment
    accepted = upload(client).json()
    path = "/api/documents/" + accepted["document_id"]
    assert client.delete(path).status_code == 409
    assert client.get(path).status_code == 200
    with Session(test_engine) as db, db.begin():
        job = db.get(ProcessingJob, UUID(accepted["job_id"]))
        job.status = "failed"
        job.error = {"code": "failed", "message": "failed", "retryable": True}
    assert client.delete(path).status_code == 204
    assert client.post("/api/processing-jobs/" + accepted["job_id"] + "/retry").status_code == 404
    assert client.delete("/api/documents/" + str(uuid4())).status_code == 404
