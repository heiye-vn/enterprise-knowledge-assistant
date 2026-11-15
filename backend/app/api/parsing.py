import logging
from typing import Annotated
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.documents import get_db
from app.importing.service import new_import_job
from app.importing.storage import ObjectStorage
from app.models import Document, DocumentContent, DocumentVersion, ProcessingJob
from app.views import processing_view

router = APIRouter(prefix="/api", tags=["parsing"])
logger = logging.getLogger(__name__)


class ReprocessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: UUID


def version_or_404(db, version_id, *, archived_job_id=None):
    available = Document.deleted_at.is_(None)
    if archived_job_id is not None:
        published = (
            select(ProcessingJob.id)
            .where(
                ProcessingJob.id == archived_job_id,
                ProcessingJob.version_id == version_id,
                ProcessingJob.job_type == "import",
                ProcessingJob.status == "ready",
            )
            .exists()
        )
        available = or_(available, published)
    version = db.scalar(
        select(DocumentVersion)
        .join(Document, DocumentVersion.document_id == Document.id)
        .where(
            DocumentVersion.id == version_id,
            available,
        )
    )
    if version is None:
        raise HTTPException(404, "文档版本不存在或已移除")
    return version


def start_processing(version_id, body, request, db, *, operation):
    settings = request.app.state.settings
    try:
        with db.begin():
            version = version_or_404(db, version_id)
            document = db.scalar(
                select(Document).where(Document.id == version.document_id).with_for_update()
            )
            if document.deleted_at is not None:
                raise HTTPException(404, "文档已移除")
            version = db.scalar(
                select(DocumentVersion)
                .where(DocumentVersion.id == version_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            existing = db.get(ProcessingJob, body.job_id)
            if existing:
                if (
                    existing.version_id != version_id
                    or existing.job_type != "import"
                    or existing.config.get("operation", "reprocess") != operation
                ):
                    raise HTTPException(409, "该重新解析标识已用于其他任务")
                identity = existing.id
            else:
                active = db.scalar(
                    select(ProcessingJob).where(
                        ProcessingJob.version_id == version_id,
                        ProcessingJob.job_type == "import",
                        ProcessingJob.status.in_(["queued", "running"]),
                    )
                )
                if active:
                    raise HTTPException(
                        409,
                        {
                            "code": "processing_active",
                            "job_id": str(active.id),
                            "message": "此版本已有解析任务，请等待完成后再重新解析",
                        },
                    )
                else:
                    identity = body.job_id
                    source_id = None
                    if operation == "reindex":
                        source_id = db.scalar(
                            select(DocumentContent.job_id)
                            .join(ProcessingJob, ProcessingJob.id == DocumentContent.job_id)
                            .where(DocumentContent.version_id == version_id)
                            .order_by(ProcessingJob.generation_no.desc())
                            .limit(1)
                        )
                        if source_id is None:
                            raise HTTPException(409, "此版本尚无解析结果，请先重新解析")
                        if settings.embedding_model in {"", "not-configured"}:
                            raise HTTPException(409, "请先配置向量模型")
                    db.add(
                        new_import_job(
                            settings,
                            version,
                            identity,
                            version.next_generation_no,
                            operation=operation,
                            source_content_job_id=source_id,
                        )
                    )
                    version.next_generation_no += 1
                    db.flush()
    except IntegrityError:
        raise HTTPException(409, "重新解析标识冲突，请刷新任务状态") from None
    if settings.dispatch_on_accept:
        from app.tasks.dispatch import dispatch_pending

        try:
            dispatch_pending(settings, job_ids=[identity])
        except Exception as error:
            logger.warning("Reprocess dispatch delayed (%s)", type(error).__name__)
    return {"job_id": str(identity), "version_id": str(version_id)}


@router.post("/document-versions/{version_id}/reprocess", status_code=202)
def reprocess(
    version_id: UUID,
    body: ReprocessRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    return start_processing(version_id, body, request, db, operation="reprocess")


@router.post("/document-versions/{version_id}/reindex", status_code=202)
def reindex(
    version_id: UUID,
    body: ReprocessRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    return start_processing(version_id, body, request, db, operation="reindex")


@router.get("/document-versions/{version_id}/parsed")
def parsed_result(
    version_id: UUID, db: Annotated[Session, Depends(get_db)], job_id: UUID | None = None
):
    version = version_or_404(db, version_id, archived_job_id=job_id)
    latest = db.scalar(
        select(ProcessingJob)
        .where(
            ProcessingJob.version_id == version_id,
            ProcessingJob.job_type == "import",
        )
        .order_by(ProcessingJob.generation_no.desc())
        .limit(1)
    )
    query = (
        select(DocumentContent, ProcessingJob)
        .join(
            ProcessingJob,
            ProcessingJob.id == DocumentContent.job_id,
        )
        .where(DocumentContent.version_id == version_id)
    )
    if job_id:
        query = query.where(DocumentContent.job_id == job_id)
    row = db.execute(query.order_by(ProcessingJob.generation_no.desc()).limit(1)).first()
    if job_id and row is None:
        raise HTTPException(404, "指定任务的解析结果不存在")
    result = None
    if row:
        content, job = row
        assets = content.artifacts.get("assets", {})
        blocks = [dict(b) for b in content.blocks]
        for block in blocks:
            if block.get("asset_id") in assets:
                block["asset_url"] = f"/api/processing-jobs/{job.id}/assets/{block['asset_id']}"
        result = {
            "job_id": str(job.id),
            "version_id": str(version_id),
            "generation_no": job.generation_no,
            "markdown": content.markdown,
            "blocks": blocks,
            "page_count": content.page_count,
            "created_at": content.created_at,
        }
    removed = db.get(Document, version.document_id).deleted_at is not None
    return {
        "result": result,
        "latest_processing": processing_view(latest),
        "document_removed": removed,
    }


@router.get("/processing-jobs/{job_id}/assets/{asset_id}")
def parsed_asset(
    job_id: UUID, asset_id: str, request: Request, db: Annotated[Session, Depends(get_db)]
):
    content = db.get(DocumentContent, job_id)
    if content is None:
        raise HTTPException(404, "解析资源不存在")
    version_or_404(db, content.version_id, archived_job_id=job_id)
    asset = content.artifacts.get("assets", {}).get(asset_id)
    if not asset or asset.get("mime_type") not in {"image/png", "image/jpeg", "image/webp"}:
        raise HTTPException(404, "解析资源不存在")
    storage = ObjectStorage(request.app.state.settings)
    try:
        metadata = storage.head(asset["object_key"])
    except (BotoCoreError, ClientError):
        raise HTTPException(503, "暂时无法读取解析资源") from None
    return StreamingResponse(
        storage.iter_bytes(asset["object_key"]),
        media_type=asset["mime_type"],
        headers={
            "Content-Length": str(metadata["ContentLength"]),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=3600",
            "Content-Security-Policy": "default-src 'none'",
        },
    )
