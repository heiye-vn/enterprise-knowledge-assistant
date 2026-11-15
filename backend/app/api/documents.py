import logging
import re
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.importing.fingerprints import DuplicateCheck, check_fingerprint
from app.importing.service import ImportProblem, ImportService
from app.importing.storage import ObjectStorage
from app.importing.validation import InvalidUpload
from app.models import Document, DocumentVersion, ProcessingJob
from app.views import document_summary

router = APIRouter(prefix="/api/documents", tags=["documents"])
files_router = APIRouter(prefix="/api/document-versions", tags=["documents"])
logger = logging.getLogger(__name__)


class FingerprintRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_sha256: str = Field(pattern=r"^[a-f0-9]{64}$", min_length=64, max_length=64)


def get_db(request: Request):
    with request.app.state.db_sessions() as db:
        yield db


@router.post("/check-duplicate", response_model=DuplicateCheck)
def check_duplicate(body: FingerprintRequest, db: Annotated[Session, Depends(get_db)]):
    try:
        return check_fingerprint(db, body.file_sha256)
    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "duplicate_check_unavailable",
                "message": "暂时无法检查重复文件，请稍后重试。",
            },
        ) from None


def _accept(request, db, document_id, file, title=None, category="未分类", *, new_version=False):
    settings = request.app.state.settings
    content = file.file.read(settings.upload_max_bytes + 1)
    service = ImportService(db, settings, ObjectStorage(settings))
    try:
        with db.begin():
            if new_version:
                accepted = service.add_version(document_id, file.filename or "", content)
            else:
                accepted = service.create(
                    document_id, file.filename or "", content, title, category
                )
    except InvalidUpload as error:
        raise HTTPException(422, str(error)) from None
    except ImportProblem as error:
        raise HTTPException(error.status_code, str(error)) from None
    except (SQLAlchemyError, BotoCoreError, ClientError):
        raise HTTPException(503, "暂时无法保存文档，请使用相同文件重试") from None
    if not accepted.duplicate and settings.dispatch_on_accept:
        from app.tasks.dispatch import dispatch_pending

        # Acceptance is durable already. Queue failure is visible and recovered by Beat.
        try:
            dispatch_pending(settings, job_ids=[accepted.job_id])
        except Exception as error:
            logger.warning("Immediate dispatch delayed (%s)", type(error).__name__)
    return JSONResponse(
        accepted.model_dump(mode="json"), status_code=200 if accepted.duplicate else 202
    )


@router.post("")
def create_document(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    document_id: Annotated[UUID, Form()],
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=300)] = None,
    category: Annotated[str, Form(max_length=80)] = "未分类",
):
    return _accept(request, db, document_id, file, title, category)


@router.post("/{document_id}/versions")
def add_version(
    document_id: UUID,
    request: Request,
    file: Annotated[UploadFile, File()],
    db: Annotated[Session, Depends(get_db)],
):
    return _accept(request, db, document_id, file, new_version=True)


@router.get("")
def list_documents(db: Annotated[Session, Depends(get_db)], offset: int = 0, limit: int = 100):
    if offset < 0 or limit < 1 or limit > 100:
        raise HTTPException(422, "分页参数无效")
    total = db.scalar(
        select(func.count()).select_from(Document).where(Document.deleted_at.is_(None))
    )
    ids = db.scalars(
        select(Document.id)
        .where(Document.deleted_at.is_(None))
        .order_by(Document.created_at.desc(), Document.id)
        .offset(offset)
        .limit(limit)
    )
    return {"items": [document_summary(db, identity) for identity in ids], "total": total}


@router.get("/{document_id}")
def get_document(document_id: UUID, db: Annotated[Session, Depends(get_db)]):
    summary = document_summary(db, document_id)
    if summary is None:
        raise HTTPException(404, "文档不存在或已移除")
    return summary


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: UUID, db: Annotated[Session, Depends(get_db)]):
    try:
        with db.begin():
            document = db.scalar(
                select(Document).where(Document.id == document_id).with_for_update()
            )
            if document is None:
                raise HTTPException(404, "文档不存在")
            if document.deleted_at is not None:
                return
            active = db.scalar(
                select(ProcessingJob.id)
                .join(DocumentVersion, ProcessingJob.version_id == DocumentVersion.id)
                .where(
                    DocumentVersion.document_id == document_id,
                    ProcessingJob.status.in_(["queued", "running"]),
                )
                .limit(1)
            )
            if active:
                raise HTTPException(409, "文档正在处理或生成图谱，请完成后再删除")
            document.deleted_at = document.updated_at = datetime.now(UTC)
            document.revision += 1
    except SQLAlchemyError:
        raise HTTPException(503, "暂时无法删除文档，请稍后重试") from None


@router.get("/{document_id}/versions")
def list_versions(document_id: UUID, db: Annotated[Session, Depends(get_db)]):
    document = db.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        raise HTTPException(404, "文档不存在或已移除")
    versions = db.scalars(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.version_no.desc())
    )
    return {
        "items": [
            {
                "id": str(v.id),
                "version_no": v.version_no,
                "filename": v.original_filename,
                "format": v.format,
                "size_bytes": v.size_bytes,
                "file_url": f"/api/document-versions/{v.id}/file",
            }
            for v in versions
        ]
    }


@files_router.api_route("/{version_id}/file", methods=["GET", "HEAD"])
def original_file(version_id: UUID, request: Request, db: Annotated[Session, Depends(get_db)]):
    version = db.get(DocumentVersion, version_id)
    if version is None:
        raise HTTPException(404, "原件不存在")
    storage = ObjectStorage(request.app.state.settings)
    key = version.file_ref.get("object_key")
    if not key:
        raise HTTPException(404, "原件暂不可用")
    try:
        metadata = storage.head(key)
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code")
        raise HTTPException(404 if code in {"404", "NoSuchKey"} else 503, "原件暂不可用") from None
    except BotoCoreError:
        raise HTTPException(503, "原件暂不可用") from None
    size = metadata["ContentLength"]
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(size),
        "Content-Type": version.file_ref.get("mime_type", "application/octet-stream"),
        "Content-Disposition": f"inline; filename*=UTF-8''{quote(version.original_filename)}",
        "ETag": f'"{version.file_sha256}"',
        "X-Content-Type-Options": "nosniff",
    }
    status, byte_range = 200, None
    if request.method != "HEAD" and (value := request.headers.get("range")):
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", value)
        if not match or not any(match.groups()):
            raise HTTPException(416, "不支持此范围", headers={"Content-Range": f"bytes */{size}"})
        left, right = match.groups()
        start = int(left) if left else max(0, size - int(right))
        end = min(int(right), size - 1) if left and right else size - 1
        if start >= size or start > end:
            raise HTTPException(416, "读取范围无效", headers={"Content-Range": f"bytes */{size}"})
        status, byte_range = 206, f"bytes={start}-{end}"
        headers.update(
            {"Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(end - start + 1)}
        )
    if request.method == "HEAD":
        return Response(status_code=200, headers=headers)
    return StreamingResponse(
        storage.iter_bytes(key, byte_range), status_code=status, headers=headers
    )
