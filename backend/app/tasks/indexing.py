"""Resumable per-job indexing; publication locks document, version, then job."""

import math
from datetime import UTC, datetime

from sqlalchemy import func, null, select
from sqlalchemy.orm import Session, undefer

from app.model_clients import ModelClient
from app.models import Chunk, Document, DocumentContent, DocumentVersion, ProcessingJob
from app.retrieval.chunking import ChunkDraft, chunk_document, validate_drafts
from app.retrieval.profile import digest_profile, embedding_text
from app.tasks.documents import live_job


class IndexingProblem(ValueError):
    def __init__(self, code, message, *, stage="chunking", retryable=False):
        super().__init__(message)
        self.code, self.stage, self.retryable = code, stage, retryable


def as_draft(chunk):
    return ChunkDraft(
        chunk.id,
        chunk.ordinal,
        chunk.content,
        chunk.content_sha256,
        chunk.heading_path,
        chunk.page_start,
        chunk.page_end,
        chunk.locators,
    )


def prepare(engine, identity, token):
    with Session(engine) as db, db.begin():
        job = live_job(db, identity, token)
        profile = job.config.get("embedding", {})
        options = job.config.get("indexing", {})
        if (
            digest_profile(profile) != job.embedding_profile_hash
            or profile.get("dimension") != job.embedding_dimension
            or profile.get("provider") != "aliyun"
            or profile.get("input_format_version") != 1
            or options.get("schema_version") != 1
        ):
            raise IndexingProblem("index_configuration_invalid", "索引配置不一致，请重建索引")
        content = db.get(DocumentContent, identity)
        if content is None:
            raise IndexingProblem("parsed_content_missing", "缺少解析结果，请重新解析")
        job.stage = "chunking"
        drafts = chunk_document(
            identity,
            content.blocks,
            **{
                k: options[k]
                for k in ("max_chars", "overlap_chars", "table_context_chars", "max_unit_chars")
            },
        )
        existing = list(
            db.scalars(
                select(Chunk)
                .options(undefer(Chunk.embedding))
                .where(Chunk.job_id == identity)
                .order_by(Chunk.ordinal)
            )
        )
        if existing:
            if [as_draft(c) for c in existing] != drafts:
                raise IndexingProblem("index_content_mismatch", "已有切片与原文不一致，请重建索引")
        else:
            for draft in drafts:
                db.add(
                    Chunk(
                        id=draft.id,
                        job_id=identity,
                        version_id=job.version_id,
                        ordinal=draft.ordinal,
                        content=draft.content,
                        content_sha256=draft.content_sha256,
                        heading_path=draft.heading_path,
                        page_start=draft.page_start,
                        page_end=draft.page_end,
                        locators=draft.locators,
                        embedding_profile_hash=job.embedding_profile_hash,
                        embedding_dimension=job.embedding_dimension,
                    )
                )
            db.flush()
        pending = list(
            db.execute(
                select(Chunk.id, Chunk.content, Chunk.heading_path)
                .where(Chunk.job_id == identity, Chunk.embedding.is_(None))
                .order_by(Chunk.ordinal)
                .limit(options["batch_size"])
            )
        )
        cp = dict(job.checkpoint)
        cp["indexing"] = {
            "prepared": True,
            "expected_chunks": len(drafts),
            "embedded_chunks": len(drafts)
            - db.scalar(
                select(func.count())
                .select_from(Chunk)
                .where(Chunk.job_id == identity, Chunk.embedding.is_(None))
            ),
        }
        job.checkpoint = cp
        job.stage = "embedding" if pending else "publishing"
        return dict(profile), pending


def run_indexing(engine, settings, identity, token):
    profile, pending = prepare(engine, identity, token)
    if pending:
        runtime = settings.model_copy(
            update={
                "embedding_model": profile["model"],
                "embedding_dimension": profile["dimension"],
            }
        )
        with ModelClient(runtime) as models:
            result = models.embed_texts(
                [embedding_text(row.content, row.heading_path) for row in pending],
                text_type="document",
            )
        if (
            result.model != profile["model"]
            or len(result.vectors) != len(pending)
            or any(
                len(vector) != profile["dimension"]
                or not any(v != 0 for v in vector)
                or any(
                    type(v) not in {int, float} or abs(v) > 3.4e38 or not math.isfinite(v)
                    for v in vector
                )
                for vector in result.vectors
            )
        ):
            raise IndexingProblem(
                "invalid_embedding_batch", "向量数量、维度或模型身份校验失败", stage="embedding"
            )
        with Session(engine) as db, db.begin():
            job = live_job(db, identity, token)
            for row, vector in zip(pending, result.vectors, strict=True):
                chunk = db.get(Chunk, row.id)
                if chunk.job_id != identity or chunk.embedding is not None:
                    raise IndexingProblem("index_content_mismatch", "切片状态发生变化，请重建索引")
                chunk.embedding = vector
            db.flush()
            missing = db.scalar(
                select(func.count())
                .select_from(Chunk)
                .where(Chunk.job_id == identity, Chunk.embedding.is_(None))
            )
            cp = dict(job.checkpoint)
            cp["indexing"] = {
                **cp["indexing"],
                "embedded_chunks": cp["indexing"]["expected_chunks"] - missing,
            }
            job.checkpoint = cp
            if missing:
                now = datetime.now(UTC)
                job.checkpoint = {**cp, "continue": True, "resume_at": now.isoformat()}
                job.status, job.stage, job.next_dispatch_at = "queued", "embedding", now
                job.lease_owner = job.lease_expires_at = None
                return
            job.stage = "publishing"
    publish_index(engine, identity, token)


def publish_index(engine, identity, token):
    with Session(engine) as db, db.begin():
        version_id = db.scalar(select(ProcessingJob.version_id).where(ProcessingJob.id == identity))
        document_id = db.scalar(
            select(DocumentVersion.document_id).where(DocumentVersion.id == version_id)
        )
        document = db.scalar(select(Document).where(Document.id == document_id).with_for_update())
        version = db.scalar(
            select(DocumentVersion).where(DocumentVersion.id == version_id).with_for_update()
        )
        job = live_job(db, identity, token)
        if document.deleted_at is not None:
            raise IndexingProblem(
                "document_removed", "文档已移除，索引不再发布", stage="publishing"
            )
        content = db.get(DocumentContent, identity)
        chunks = list(
            db.scalars(
                select(Chunk)
                .options(undefer(Chunk.embedding))
                .where(Chunk.job_id == identity)
                .order_by(Chunk.ordinal)
            )
        )
        validate_drafts(content.blocks, [as_draft(c) for c in chunks])
        if (
            not chunks
            or len(chunks) != job.checkpoint["indexing"]["expected_chunks"]
            or any(
                c.embedding is None or len(c.embedding) != job.embedding_dimension for c in chunks
            )
        ):
            raise IndexingProblem(
                "incomplete_index", "向量尚未全部完成，无法发布", stage="publishing"
            )
        job.status, job.stage = "ready", "done"
        job.finished_at = datetime.now(UTC)
        job.error = null()
        job.lease_owner = job.lease_expires_at = None
        previous = (
            db.get(ProcessingJob, version.active_import_job_id)
            if version.active_import_job_id
            else None
        )
        version_changed = previous is None or job.generation_no > previous.generation_no
        if version_changed:
            version.active_import_job_id = identity
        current = (
            db.get(DocumentVersion, document.current_version_id)
            if document.current_version_id
            else None
        )
        current_job = (
            db.get(ProcessingJob, current.active_import_job_id)
            if current and current.active_import_job_id
            else None
        )
        current_order = (
            (current.version_no, current_job.generation_no if current_job else 0)
            if current
            else (0, 0)
        )
        if (
            version.active_import_job_id == identity
            and (version.version_no, job.generation_no) >= current_order
        ):
            if document.current_version_id != version_id or version_changed:
                document.current_version_id = version_id
                document.revision += 1
                document.updated_at = datetime.now(UTC)
