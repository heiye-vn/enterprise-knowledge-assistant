import logging
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import null, select
from sqlalchemy.orm import Session

from app.api.documents import get_db
from app.models import Document, DocumentVersion, ProcessingJob

router = APIRouter(prefix="/api/processing-jobs", tags=["jobs"])
logger = logging.getLogger(__name__)


@router.get("/{job_id}")
def get_job(job_id: UUID, db: Annotated[Session, Depends(get_db)]):
    job = db.get(ProcessingJob, job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    return {
        key: getattr(job, key)
        for key in (
            "id",
            "version_id",
            "job_type",
            "status",
            "stage",
            "error",
            "attempt_no",
            "max_attempts",
            "next_dispatch_at",
            "last_dispatched_at",
            "dispatch_attempts",
        )
    }


@router.post("/{job_id}/retry")
def retry_job(job_id: UUID, request: Request, db: Annotated[Session, Depends(get_db)]):
    with db.begin():
        version_id = db.scalar(
            select(ProcessingJob.version_id).where(
                ProcessingJob.id == job_id, ProcessingJob.job_type == "import"
            )
        )
        document_id = db.scalar(
            select(DocumentVersion.document_id).where(DocumentVersion.id == version_id)
        )
        document = db.scalar(select(Document).where(Document.id == document_id).with_for_update())
        if document is None or document.deleted_at is not None:
            raise HTTPException(404, "任务不存在")
        db.scalar(select(DocumentVersion).where(DocumentVersion.id == version_id).with_for_update())
        job = db.scalar(
            select(ProcessingJob)
            .where(ProcessingJob.id == job_id, ProcessingJob.job_type == "import")
            .with_for_update()
        )
        if job is None:
            raise HTTPException(404, "任务不存在")
        if (
            job.status != "failed"
            or not (job.error or {}).get("retryable")
            or job.attempt_no >= job.max_attempts
        ):
            raise HTTPException(409, "当前任务不支持重试或已达到次数上限")
        active = db.scalar(
            select(ProcessingJob.id)
            .where(
                ProcessingJob.version_id == job.version_id,
                ProcessingJob.job_type == "import",
                ProcessingJob.status.in_(["queued", "running"]),
                ProcessingJob.id != job_id,
            )
            .limit(1)
        )
        if active:
            raise HTTPException(409, "此版本已有处理任务，请等待当前任务结束")
        job.status, job.stage = "queued", "queued"
        job.error, job.finished_at = null(), None
        job.lease_owner = job.lease_expires_at = None
        job.next_dispatch_at = datetime.now(UTC)
    settings = request.app.state.settings
    if settings.dispatch_on_accept:
        from app.tasks.dispatch import dispatch_pending

        try:
            dispatch_pending(settings, job_ids=[job_id])
        except Exception as error:
            logger.warning("Retry dispatch delayed (%s)", type(error).__name__)
    return {"job_id": str(job_id), "status": "queued"}
