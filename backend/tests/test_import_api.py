"""Real PG/RustFS acceptance tests, isolated from the application's documents."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


@pytest.fixture
def import_environment(test_engine):
    from app.config import Settings
    from app.importing.storage import ObjectStorage
    from app.main import create_app
    from app.models import Chunk, Document, DocumentContent, DocumentVersion, ProcessingJob

    prefix = f"integration/import/{uuid4()}"
    original = Settings()
    settings = original.model_copy(
        update={
            "database_url": original.database_url.__class__(
                test_engine.url.render_as_string(hide_password=False)
            ),
            "original_prefix": prefix,
            "parsed_prefix": prefix + "-parsed",
            "dispatch_on_accept": False,
            "embedding_model": "not-configured",
            "langsmith_tracing": False,
        }
    )
    storage = ObjectStorage(settings)
    with TestClient(create_app(settings)) as client:
        yield client, settings, storage
    with Session(test_engine) as db, db.begin():
        versions = list(
            db.scalars(
                select(DocumentVersion).where(
                    DocumentVersion.file_ref["object_key"].astext.startswith(prefix + "/")
                )
            )
        )
        ids = [v.id for v in versions]
        document_ids = [v.document_id for v in versions]
        for doc in db.scalars(select(Document).where(Document.id.in_(document_ids))):
            doc.current_version_id = None
        for version in versions:
            version.active_import_job_id = None
        db.flush()
        db.execute(delete(Chunk).where(Chunk.version_id.in_(ids)))
        db.execute(delete(DocumentContent).where(DocumentContent.version_id.in_(ids)))
        db.execute(delete(ProcessingJob).where(ProcessingJob.version_id.in_(ids)))
        db.execute(delete(DocumentVersion).where(DocumentVersion.id.in_(ids)))
        db.execute(delete(Document).where(Document.id.in_(document_ids)))
    for item in storage.list_originals():
        storage.delete(item["key"])
    for item in storage.list_objects(settings.parsed_prefix):
        storage.delete(item["key"])


def upload(client, content=b"# policy\nOriginal text.", *, document_id=None, filename="policy.md"):
    return client.post(
        "/api/documents",
        data={"document_id": str(document_id or uuid4())},
        files={"file": (filename, content)},
    )


def test_upload_survives_refresh_and_supports_original_head_and_ranges(import_environment):
    client, *_ = import_environment
    content = "%PDF-1.7\n真实原件字节。".encode()
    result = upload(client, content, filename="制度.pdf")
    assert result.status_code == 202, result.text
    value = result.json()
    assert not value["duplicate"]
    listing = client.get("/api/documents").json()
    doc = next(d for d in listing["items"] if d["id"] == value["document_id"])
    assert doc["filename"] == "制度.pdf"
    assert doc["can_query"] is False
    assert not {"markdown", "blocks", "pages", "embedding"}.intersection(doc)
    path = f"/api/document-versions/{value['version_id']}/file"
    assert client.get(path).content == content
    head = client.head(path)
    assert head.status_code == 200 and head.content == b""
    assert int(head.headers["content-length"]) == len(content)
    assert head.headers["accept-ranges"] == "bytes"
    assert "filename*=UTF-8''" in head.headers["content-disposition"]
    part = client.get(path, headers={"Range": "bytes=1-5"})
    assert part.status_code == 206 and part.content == content[1:6]
    assert part.headers["content-range"] == f"bytes 1-5/{len(content)}"
    assert client.get(path, headers={"Range": "bytes=-3"}).content == content[-3:]
    assert client.get(path, headers={"Range": "bytes=9999-"}).status_code == 416
    assert client.get(f"/api/documents/{value['document_id']}").status_code == 200


def test_duplicate_or_renamed_upload_does_not_create_more_objects_or_jobs(import_environment):
    client, _, storage = import_environment
    first = upload(client)
    before = len(list(storage.list_originals()))
    duplicate = upload(client, filename="renamed.md")
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"]
    for key in ["document_id", "version_id", "job_id"]:
        assert duplicate.json()[key] == first.json()[key]
    assert len(list(storage.list_originals())) == before


def test_stable_id_retry_conflict_and_explicit_new_version(import_environment):
    client, *_ = import_environment
    identity = uuid4()
    first = upload(client, document_id=identity).json()
    assert upload(client, document_id=identity).json()["version_id"] == first["version_id"]
    assert upload(client, b"changed", document_id=identity).status_code == 409
    updated = client.post(
        f"/api/documents/{identity}/versions", files={"file": ("new.md", b"# new policy")}
    )
    assert updated.status_code == 202
    assert updated.json()["version_id"] != first["version_id"]
    versions = client.get(f"/api/documents/{identity}/versions").json()["items"]
    assert [v["version_no"] for v in versions] == [2, 1]
    assert (
        client.get(f"/api/document-versions/{first['version_id']}/file").content
        == b"# policy\nOriginal text."
    )


def test_two_concurrent_requests_accept_only_one_copy(import_environment):
    client, _, storage = import_environment
    content = f"# Concurrent {uuid4()}".encode()
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: upload(client, content), range(2)))
    assert sorted(r.status_code for r in results) == [200, 202]
    assert results[0].json()["document_id"] == results[1].json()["document_id"]
    assert len(list(storage.list_originals())) == 1


def test_deleted_document_does_not_block_reimport(import_environment, test_engine):
    from app.models import Document

    client, *_ = import_environment
    first = upload(client).json()
    with Session(test_engine) as db, db.begin():
        db.get(Document, first["document_id"]).deleted_at = datetime.now(UTC)
    second = upload(client)
    assert second.status_code == 202
    assert second.json()["document_id"] != first["document_id"]


def test_invalid_upload_does_not_store_any_original(import_environment):
    client, _, storage = import_environment
    assert upload(client, b"not a pdf", filename="invalid.pdf").status_code == 422
    assert list(storage.list_originals()) == []
