from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.orm import Session
from test_import_api import import_environment as import_environment
from test_import_api import upload

pytestmark = pytest.mark.integration


def test_failed_publish_is_durable_and_can_be_dispatched_again(import_environment, test_engine):
    from app.models import ProcessingJob
    from app.tasks.dispatch import dispatch_pending

    client, settings, _ = import_environment
    accepted = upload(client).json()
    job_id = UUID(accepted["job_id"])

    def unavailable(_identity):
        raise ConnectionError("broker unavailable")

    assert dispatch_pending(settings, publisher=unavailable) == 0
    with Session(test_engine) as db, db.begin():
        job = db.get(ProcessingJob, job_id)
        assert job.status == "queued" and job.dispatch_attempts == 1
        assert job.error["code"] == "queue_unavailable"
        assert job.next_dispatch_at > datetime.now(UTC)
        job.next_dispatch_at = datetime.now(UTC) - timedelta(seconds=1)
    published = []
    assert dispatch_pending(settings, publisher=published.append) == 1
    assert published == [job_id]


def test_worker_parses_markdown_and_duplicate_message_does_not_reprocess(import_environment):
    from app.tasks.documents import process_document

    client, settings, _ = import_environment
    accepted = upload(client).json()
    process_document(accepted["job_id"], settings)
    first = client.get(f"/api/processing-jobs/{accepted['job_id']}").json()
    assert first["status"] == "failed" and first["error"]["code"] == "index_not_configured"
    assert first["error"]["retryable"] is False
    process_document(accepted["job_id"], settings)
    second = client.get(f"/api/processing-jobs/{accepted['job_id']}").json()
    assert second["attempt_no"] == first["attempt_no"] == 1
    assert client.get(f"/api/documents/{accepted['document_id']}").json()["can_query"] is False
    assert client.get(f"/api/document-versions/{accepted['version_id']}/file").status_code == 200


def test_dispatch_success_is_recorded_even_if_worker_finishes_before_publish_returns(
    import_environment,
):
    from app.tasks.dispatch import dispatch_pending
    from app.tasks.documents import process_document

    client, settings, _ = import_environment
    accepted = upload(client).json()
    dispatch_pending(settings, publisher=lambda identity: process_document(str(identity), settings))
    job = client.get(f"/api/processing-jobs/{accepted['job_id']}").json()
    assert job["last_dispatched_at"] is not None
    assert job["error"]["code"] == "index_not_configured"


def test_retry_keeps_attempt_count_and_obeys_limit(import_environment, test_engine, monkeypatch):
    from app.importing.storage import ObjectStorage
    from app.models import ProcessingJob
    from app.tasks.documents import process_document

    client, settings, _ = import_environment
    accepted = upload(client).json()

    def unavailable(*args):
        raise OSError("storage unavailable")

    monkeypatch.setattr(ObjectStorage, "read", unavailable)
    process_document(accepted["job_id"], settings)
    endpoint = f"/api/processing-jobs/{accepted['job_id']}"
    assert client.get(endpoint).json()["error"]["retryable"]
    assert client.post(endpoint + "/retry").status_code == 200
    assert client.get(endpoint).json()["attempt_no"] == 1
    assert client.post(endpoint + "/retry").status_code == 409
    with Session(test_engine) as db, db.begin():
        job = db.get(ProcessingJob, UUID(accepted["job_id"]))
        job.max_attempts = 2
    process_document(accepted["job_id"], settings)
    assert client.get(endpoint).json()["attempt_no"] == 2
    assert client.post(endpoint + "/retry").status_code == 409
    assert upload(client).json()["job_id"] == accepted["job_id"]
    assert client.get(endpoint).json()["attempt_no"] == 2


def test_expired_lease_recovery_rejects_stale_worker(import_environment, test_engine):
    from app.models import ProcessingJob
    from app.tasks.dispatch import recover_expired
    from app.tasks.documents import claim_job, fail_job

    client, settings, _ = import_environment
    identity = UUID(upload(client).json()["job_id"])
    token = claim_job(settings, identity)
    assert token is not None
    with Session(test_engine) as db, db.begin():
        db.get(ProcessingJob, identity).lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert recover_expired(settings) == 1
    assert not fail_job(settings, identity, token, {"code": "stale", "retryable": False})
    next_token = claim_job(settings, identity)
    assert next_token > token
    assert fail_job(settings, identity, next_token, {"code": "current", "retryable": False})


def test_orphan_cleanup_preserves_referenced_originals_and_retention(import_environment):
    from app.tasks.dispatch import cleanup_orphans

    client, settings, storage = import_environment
    upload(client)
    orphan = f"{settings.original_prefix}/orphan.md"
    storage.put(orphan, b"orphan", "text/markdown", "a" * 64)
    assert cleanup_orphans(settings) == 0
    assert cleanup_orphans(settings, cutoff=datetime.now(UTC) + timedelta(seconds=5)) == 1
    assert len(list(storage.list_originals())) == 1
