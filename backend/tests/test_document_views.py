from datetime import UTC, datetime
from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration


def test_ready_document_summary_matches_reader_metadata_without_full_text(db, source):
    from app.views import document_summary

    document, version, job, _ = source
    job.status, job.stage, job.finished_at = "ready", "done", datetime.now(UTC)
    db.flush()
    version.active_import_job_id = job.id
    document.current_version_id = version.id
    db.flush()
    summary = document_summary(db, document.id)
    assert summary.title == "费用报销管理制度"
    assert summary.category == "财务制度"
    assert summary.filename == "费用制度.pdf"
    assert summary.version_label == "1.1"
    assert summary.page_count == 4
    assert summary.status == "ready"
    assert summary.can_query is True
    assert not {"pages", "markdown", "blocks", "embedding"}.intersection(summary.model_dump())


def test_failed_new_version_keeps_existing_ready_document_usable(db, source):
    from app.models import DocumentVersion, ProcessingJob
    from app.views import document_summary

    document, version, job, _ = source
    job.status, job.stage, job.finished_at = "ready", "done", datetime.now(UTC)
    db.flush()
    version.active_import_job_id = job.id
    document.current_version_id = version.id
    new_version = DocumentVersion(
        id=uuid4(),
        document_id=document.id,
        version_no=2,
        version_label="1.2",
        original_filename="新版.pdf",
        format="pdf",
        size_bytes=200,
        file_sha256="f" * 64,
        file_ref={},
    )
    db.add(new_version)
    db.flush()
    db.add(
        ProcessingJob(
            id=uuid4(),
            version_id=new_version.id,
            generation_no=1,
            job_type="import",
            status="failed",
            stage="parsing",
            config={},
            config_hash="a" * 64,
            embedding_profile_hash="c" * 64,
            embedding_dimension=3,
        )
    )
    db.flush()
    summary = document_summary(db, document.id)
    assert summary.status == "ready"
    assert summary.can_query is True
    assert summary.version_id == version.id
    assert summary.latest_processing["status"] == "failed"
    assert summary.latest_processing["version_id"] == str(new_version.id)


def test_markdown_summary_does_not_invent_page_count(db, source):
    from app.models import DocumentContent
    from app.views import document_summary

    document, version, job, _ = source
    version.format = "md"
    db.get(DocumentContent, job.id).page_count = None
    job.status, job.stage, job.finished_at = "ready", "done", datetime.now(UTC)
    db.flush()
    version.active_import_job_id = job.id
    document.current_version_id = version.id
    db.flush()
    assert document_summary(db, document.id).page_count is None
