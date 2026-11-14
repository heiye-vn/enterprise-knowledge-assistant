"""Read models for the prototype; list metadata never contains parsed pages or vectors."""

from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.contracts import import_display_status
from app.models import Document, DocumentContent, DocumentVersion, ProcessingJob


class DocumentSummary(BaseModel):
    id: UUID
    title: str
    category: str
    filename: str | None
    size_bytes: int | None
    version_id: UUID | None
    version_label: str | None
    page_count: int | None
    status: str
    can_query: bool
    latest_processing: dict | None


def document_summary(db: Session, document_id: UUID) -> DocumentSummary | None:
    active = aliased(ProcessingJob)
    row = (
        db.execute(
            select(
                Document.id,
                Document.title,
                Document.category,
                DocumentVersion.id.label("version_id"),
                DocumentVersion.original_filename,
                DocumentVersion.size_bytes,
                DocumentVersion.version_label,
                DocumentContent.page_count,
                active.id.label("active_job_id"),
                active.status.label("active_status"),
                active.job_type.label("active_type"),
            )
            .outerjoin(
                DocumentVersion,
                Document.current_version_id == DocumentVersion.id,
            )
            .outerjoin(active, DocumentVersion.active_import_job_id == active.id)
            .outerjoin(
                DocumentContent,
                DocumentContent.job_id == active.id,
            )
            .where(Document.id == document_id, Document.deleted_at.is_(None))
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    latest = (
        db.execute(
            select(
                ProcessingJob.id,
                ProcessingJob.status,
                ProcessingJob.stage,
                DocumentVersion.id.label("version_id"),
                DocumentVersion.version_label,
                DocumentVersion.original_filename,
                DocumentVersion.size_bytes,
            )
            .join(DocumentVersion, ProcessingJob.version_id == DocumentVersion.id)
            .where(
                DocumentVersion.document_id == document_id,
                ProcessingJob.job_type == "import",
            )
            .order_by(DocumentVersion.version_no.desc(), ProcessingJob.generation_no.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    can_query = row["active_status"] == "ready" and row["active_type"] == "import"
    display = (
        "ready"
        if can_query
        else (import_display_status(latest["status"], latest["stage"]) if latest else "queued")
    )
    values = row if row["version_id"] is not None else (latest or row)
    latest_processing = None
    if latest and latest["id"] != row["active_job_id"]:
        latest_processing = {
            "job_id": str(latest["id"]),
            "version_id": str(latest["version_id"]),
            "status": latest["status"],
            "stage": latest["stage"],
            "display_status": import_display_status(latest["status"], latest["stage"]),
        }
    return DocumentSummary(
        id=row["id"],
        title=row["title"],
        category=row["category"],
        filename=values["original_filename"],
        size_bytes=values["size_bytes"],
        version_id=values["version_id"],
        version_label=values["version_label"],
        page_count=row["page_count"],
        status=display,
        can_query=can_query,
        latest_processing=latest_processing,
    )
