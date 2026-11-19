"""Exact file identity across all versions of documents still in the library.

The preflight query is advisory. An import writer must call lock_and_check_file
before storage/registration and keep that transaction open through its DB writes.
All import writers use this boundary, under PostgreSQL READ COMMITTED isolation.
"""

import hashlib
import re
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Document, DocumentVersion


class ExistingDocument(BaseModel):
    document_id: UUID
    version_id: UUID
    title: str
    filename: str
    version_no: int


class DuplicateCheck(BaseModel):
    file_sha256: str
    duplicate: bool
    existing: ExistingDocument | None


# 后端自己重新计算文件指纹
def file_fingerprint(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


# SQL 查重逻辑
def check_fingerprint(db: Session, file_sha256: str) -> DuplicateCheck:
    if not re.fullmatch(r"[a-f0-9]{64}", file_sha256):
        raise ValueError("Invalid SHA-256 fingerprint")
    row = (
        db.execute(
            select(
                Document.id.label("document_id"),
                Document.title,
                DocumentVersion.id.label("version_id"),
                DocumentVersion.original_filename.label("filename"),
                DocumentVersion.version_no,
            )
            .join(DocumentVersion, DocumentVersion.document_id == Document.id)
            .where(
                DocumentVersion.file_sha256 == file_sha256,  # 哈希对比
                Document.deleted_at.is_(None),  # 查询未删除的文档
            )
            .order_by(Document.created_at, Document.id, DocumentVersion.version_no)
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    existing = ExistingDocument.model_validate(dict(row)) if row is not None else None
    return DuplicateCheck(
        file_sha256=file_sha256, duplicate=existing is not None, existing=existing
    )


# 取 SHA-256 前 8 字节执行
def lock_and_check_file(db: Session, content: bytes) -> DuplicateCheck:
    """Recompute server-side and serialize same-file writers until commit/rollback.

    A match must return the existing record, without inserting another document,
    version or processing job. Never trust a client-provided hash at this boundary.
    This function does not commit, upload an object, or start a processing job.
    """
    file_sha256 = file_fingerprint(content)
    lock_key = int.from_bytes(bytes.fromhex(file_sha256)[:8], "big", signed=True)
    # pg_advisory_xact_lock：数据库排他锁，防止高并发冲突
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    return check_fingerprint(db, file_sha256)
