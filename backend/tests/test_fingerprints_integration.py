"""Use real PG to catch missed historical versions, soft deletes and concurrent uploads."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


def test_global_duplicate_api_returns_existing_document_with_a_different_request_id(db, source):
    from app.api.documents import get_db
    from app.main import create_app

    document, version, *_ = source
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        result = client.post(
            "/api/documents/check-duplicate", json={"file_sha256": version.file_sha256}
        )
    assert result.status_code == 200
    assert result.json() == {
        "file_sha256": version.file_sha256,
        "duplicate": True,
        "existing": {
            "document_id": str(document.id),
            "version_id": str(version.id),
            "title": document.title,
            "filename": version.original_filename,
            "version_no": 1,
        },
    }


def test_check_covers_historical_versions_and_excludes_deleted_documents(db, source):
    from app.importing.fingerprints import check_fingerprint
    from app.models import DocumentVersion

    document, version, *_ = source
    newer = DocumentVersion(
        id=uuid4(),
        document_id=document.id,
        version_no=2,
        original_filename="新版.pdf",
        format="pdf",
        size_bytes=100,
        file_sha256="f" * 64,
        file_ref={},
    )
    db.add(newer)
    db.flush()
    document.current_version_id = newer.id
    db.flush()
    match = check_fingerprint(db, version.file_sha256)
    assert match.duplicate
    assert match.existing.version_id == version.id
    document.deleted_at = datetime.now(UTC)
    db.flush()
    assert not check_fingerprint(db, version.file_sha256).duplicate
    assert not check_fingerprint(db, "0" * 64).duplicate


def test_concurrent_creators_using_import_guard_only_register_one_file(test_engine):
    from app.importing.fingerprints import lock_and_check_file
    from app.models import Document, DocumentVersion

    content = f"# 唯一制度 {uuid4()}".encode()
    document_ids = [uuid4(), uuid4()]
    barrier = Barrier(2)

    def create(document_id):
        with Session(test_engine) as db, db.begin():
            barrier.wait(timeout=10)
            result = lock_and_check_file(db, content)
            if result.duplicate:
                return result.existing.document_id
            db.add(Document(id=document_id, title="并发上传测试"))
            db.flush()
            db.add(
                DocumentVersion(
                    id=uuid4(),
                    document_id=document_id,
                    version_no=1,
                    original_filename="任意文件名.md",
                    format="md",
                    size_bytes=len(content),
                    file_sha256=result.file_sha256,
                    file_ref={},
                )
            )
            db.flush()
            return document_id

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(create, document_ids))
        assert results[0] == results[1]
        with Session(test_engine) as db:
            count = db.scalar(
                select(func.count())
                .select_from(DocumentVersion)
                .where(DocumentVersion.document_id.in_(document_ids))
            )
            assert count == 1
    finally:
        with Session(test_engine) as db, db.begin():
            db.execute(delete(DocumentVersion).where(DocumentVersion.document_id.in_(document_ids)))
            db.execute(delete(Document).where(Document.id.in_(document_ids)))
