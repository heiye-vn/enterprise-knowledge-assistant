"""Validated persistence boundaries; callers own the surrounding transaction.

No parsing, retrieval or model generation is performed here.
"""

import re
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import SessionScope
from app.models import (
    ChatMessage,
    ChatSession,
    Chunk,
    Document,
    DocumentVersion,
    MessageCitation,
    ProcessingJob,
)


class CitationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    chunk_id: UUID
    citation_no: int = Field(gt=0)
    quote: str = Field(min_length=1)


def save_scope(db: Session, session_id: UUID, scope: SessionScope, expected_revision: int):
    session = db.scalar(
        select(ChatSession)
        .where(
            ChatSession.id == session_id,
            ChatSession.deleted_at.is_(None),
        )
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if session is None or session.scope_revision != expected_revision:
        raise ValueError("会话不存在或问答范围已变更，请刷新后重试")
    if scope.mode == "custom":
        available = set(
            db.scalars(
                select(Document.id)
                .join(
                    DocumentVersion,
                    Document.current_version_id == DocumentVersion.id,
                )
                .join(ProcessingJob, DocumentVersion.active_import_job_id == ProcessingJob.id)
                .where(
                    Document.id.in_(scope.document_ids),
                    Document.deleted_at.is_(None),
                    ProcessingJob.job_type == "import",
                    ProcessingJob.status == "ready",
                )
            )
        )
        if available != set(scope.document_ids):
            raise ValueError("所选文档不存在、已移除或尚不可问答")
    session.scope = scope.model_dump(mode="json")
    session.scope_revision += 1
    session.updated_at = datetime.now(UTC)
    db.flush()


def complete_answer(
    db: Session,
    message_id: UUID,
    content: str,
    citations: list[dict],
    *,
    answer_kind: Literal["answered", "partially_answered", "refused"],
):
    """Commit-ready final text and verified citations together; never commit the caller's work."""
    if answer_kind not in {"answered", "partially_answered", "refused"} or not content.strip():
        raise ValueError("回答类型或正文无效")
    inputs = [CitationInput.model_validate(item) for item in citations]
    numbers = [item.citation_no for item in inputs]
    if len(numbers) != len(set(numbers)):
        raise ValueError("引用编号不能重复")
    if set(numbers) != {int(n) for n in re.findall(r"\[(\d+)\]", content)}:
        raise ValueError("正文引用编号与最终来源不一致")
    if answer_kind != "refused" and not inputs:
        raise ValueError("有据回答至少需要一条引用")
    with db.begin_nested():
        message = db.scalar(
            select(ChatMessage)
            .where(
                ChatMessage.id == message_id,
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if message is None or message.role != "assistant":
            raise ValueError("最终回答必须属于助手消息")
        if message.status not in {"queued", "retrieving", "generating"}:
            raise ValueError("消息已进入终态")
        snapshot = message.request_snapshot or {}
        allowed = {
            (item.get("document_id"), item.get("version_id"), item.get("job_id"))
            for item in snapshot.get("documents", [])
        }
        records = []
        for item in inputs:
            row = db.execute(
                select(Chunk, DocumentVersion, Document)
                .join(
                    DocumentVersion,
                    Chunk.version_id == DocumentVersion.id,
                )
                .join(Document, DocumentVersion.document_id == Document.id)
                .where(
                    Chunk.id == item.chunk_id,
                )
            ).one_or_none()
            if row is None:
                raise ValueError("来源切片不存在")
            chunk, version, document = row
            if (str(document.id), str(version.id), str(chunk.job_id)) not in allowed:
                raise ValueError("来源切片不在本轮固定的资料范围内")
            if item.quote not in chunk.content:
                raise ValueError("引文与实际切片不一致")
            records.append(
                MessageCitation(
                    id=uuid4(),
                    message_id=message.id,
                    chunk_id=chunk.id,
                    citation_no=item.citation_no,
                    quote=item.quote,
                    source_snapshot={
                        "document_id": str(document.id),
                        "version_id": str(version.id),
                        "job_id": str(chunk.job_id),
                        "document_title": document.title,
                        "version_label": version.version_label,
                        "heading_path": chunk.heading_path,
                        "page_start": chunk.page_start,
                        "page_end": chunk.page_end,
                        "locators": chunk.locators,
                    },
                )
            )
        db.add_all(records)
        message.content, message.answer_kind, message.status = content, answer_kind, "completed"
        message.updated_at = datetime.now(UTC)
        message.lease_expires_at = None
        db.flush()
