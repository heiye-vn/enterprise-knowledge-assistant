"""Eight core ORM entities; schema changes are managed by Alembic."""

from datetime import datetime
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    CHAR,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("btrim(title) <> ''"),
        CheckConstraint("btrim(category) <> ''"),
        CheckConstraint("next_version_no > 0"),
        CheckConstraint("revision >= 0"),
        ForeignKeyConstraint(
            ["current_version_id", "id"],
            ["document_versions.id", "document_versions.document_id"],
            ondelete="RESTRICT",
            name="fk_documents_current_version",
            use_alter=True,
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str] = mapped_column(
        String(80), nullable=False, server_default=text("'未分类'")
    )
    current_version_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    next_version_no: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        CheckConstraint("version_no > 0"),
        CheckConstraint("format IN ('pdf', 'docx', 'md')"),
        CheckConstraint("size_bytes > 0"),
        CheckConstraint("file_sha256 ~ '^[0-9a-f]{64}$'"),
        CheckConstraint("jsonb_typeof(file_ref) = 'object'"),
        CheckConstraint("jsonb_typeof(source_metadata) = 'object'"),
        CheckConstraint("next_generation_no > 0"),
        UniqueConstraint("document_id", "version_no"),
        UniqueConstraint("document_id", "file_sha256"),
        UniqueConstraint("id", "document_id"),
        ForeignKeyConstraint(
            ["active_import_job_id", "id"],
            ["processing_jobs.id", "processing_jobs.version_id"],
            ondelete="RESTRICT",
            name="fk_versions_active_import",
            use_alter=True,
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, nullable=False)
    document_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    version_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    format: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    file_ref: Mapped[dict] = mapped_column(
        JSONB(none_as_null=True).evaluates_none(), nullable=False
    )
    source_metadata: Mapped[dict] = mapped_column(
        JSONB(none_as_null=True).evaluates_none(), nullable=False, server_default=text("'{}'")
    )
    active_import_job_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    next_generation_no: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (
        ForeignKeyConstraint(["version_id"], ["document_versions.id"], ondelete="RESTRICT"),
        CheckConstraint("job_type IN ('import', 'graph')"),
        CheckConstraint("generation_no > 0"),
        CheckConstraint("status IN ('queued', 'running', 'ready', 'failed', 'canceled')"),
        CheckConstraint(
            "stage IN ('queued', 'parsing', 'chunking', 'embedding', 'publishing', "
            "'extracting', 'validating', 'projecting', 'done')"
        ),
        CheckConstraint("jsonb_typeof(config) = 'object'"),
        CheckConstraint("config_hash ~ '^[0-9a-f]{64}$'"),
        CheckConstraint("jsonb_typeof(checkpoint) = 'object'"),
        CheckConstraint("attempt_no >= 0"),
        CheckConstraint("max_attempts > 0"),
        CheckConstraint("lease_token >= 0"),
        CheckConstraint("dispatch_attempts >= 0"),
        CheckConstraint("jsonb_typeof(error) = 'object'"),
        UniqueConstraint("version_id", "generation_no"),
        UniqueConstraint("id", "version_id"),
        UniqueConstraint("id", "version_id", "embedding_profile_hash", "embedding_dimension"),
        ForeignKeyConstraint(
            ["source_job_id", "version_id"],
            ["processing_jobs.id", "processing_jobs.version_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("(lease_owner IS NULL) = (lease_expires_at IS NULL)"),
        CheckConstraint("source_job_id IS NULL OR source_job_id <> id"),
        CheckConstraint(
            "(job_type = 'import' AND source_job_id IS NULL AND embedding_profile_hash IS "
            "NOT NULL AND embedding_profile_hash ~ '^[0-9a-f]{64}$' AND "
            "embedding_dimension IS NOT NULL AND embedding_dimension > 0) OR (job_type = "
            "'graph' AND source_job_id IS NOT NULL AND embedding_profile_hash IS NULL AND "
            "embedding_dimension IS NULL)"
        ),
        CheckConstraint(
            "stage IN ('queued', 'done') OR (job_type = 'import' AND stage IN ('parsing', "
            "'chunking', 'embedding', 'publishing')) OR (job_type = 'graph' AND stage IN "
            "('extracting', 'validating', 'projecting'))"
        ),
        CheckConstraint("status <> 'ready' OR (stage = 'done' AND finished_at IS NOT NULL)"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, nullable=False)
    version_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_job_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    generation_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    stage: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    config: Mapped[dict] = mapped_column(JSONB(none_as_null=True).evaluates_none(), nullable=False)
    config_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    embedding_profile_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    embedding_dimension: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    checkpoint: Mapped[dict] = mapped_column(
        JSONB(none_as_null=True).evaluates_none(), nullable=False, server_default=text("'{}'")
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("3")
    )
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_token: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_dispatch_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dispatch_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    error: Mapped[dict | None] = mapped_column(
        JSONB(none_as_null=True).evaluates_none(), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class DocumentContent(Base):
    __tablename__ = "document_contents"
    __table_args__ = (
        CheckConstraint("jsonb_typeof(blocks) = 'array'"),
        CheckConstraint("jsonb_typeof(artifacts) = 'object'"),
        CheckConstraint("page_count > 0"),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'"),
        ForeignKeyConstraint(
            ["job_id", "version_id"],
            ["processing_jobs.id", "processing_jobs.version_id"],
            ondelete="RESTRICT",
        ),
    )
    job_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, nullable=False)
    version_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    markdown: Mapped[str] = mapped_column(Text, nullable=False, deferred=True)
    blocks: Mapped[list[dict]] = mapped_column(
        JSONB(none_as_null=True).evaluates_none(),
        nullable=False,
        server_default=text("'[]'"),
        deferred=True,
    )
    artifacts: Mapped[dict] = mapped_column(
        JSONB(none_as_null=True).evaluates_none(), nullable=False, server_default=text("'{}'")
    )
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        CheckConstraint("ordinal >= 0"),
        CheckConstraint("btrim(content) <> ''"),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'"),
        CheckConstraint("jsonb_typeof(locators) = 'array'"),
        CheckConstraint("embedding_dimension > 0"),
        UniqueConstraint("job_id", "ordinal"),
        ForeignKeyConstraint(
            ["job_id", "version_id", "embedding_profile_hash", "embedding_dimension"],
            [
                "processing_jobs.id",
                "processing_jobs.version_id",
                "processing_jobs.embedding_profile_hash",
                "processing_jobs.embedding_dimension",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(page_start IS NULL AND page_end IS NULL) OR (page_start IS NOT NULL AND "
            "page_end IS NOT NULL AND page_start >= 1 AND page_end >= page_start)"
        ),
        CheckConstraint("embedding IS NULL OR vector_dims(embedding) = embedding_dimension"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, nullable=False)
    job_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    version_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    heading_path: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    locators: Mapped[list[dict]] = mapped_column(
        JSONB(none_as_null=True).evaluates_none(), nullable=False, server_default=text("'[]'")
    )
    embedding_profile_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(), nullable=True, deferred=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (
        CheckConstraint("btrim(title) <> ''"),
        CheckConstraint(
            "jsonb_typeof(scope) = 'object' AND scope ? 'mode' AND scope ? 'document_ids' "
            "AND scope ->> 'mode' IS NOT NULL AND scope ->> 'mode' IN ('all', 'custom') "
            "AND jsonb_typeof(scope -> 'document_ids') = 'array'"
        ),
        CheckConstraint("scope_revision >= 0"),
        CheckConstraint("next_message_seq > 0"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False, server_default=text("'新会话'"))
    scope: Mapped[dict] = mapped_column(
        JSONB(none_as_null=True).evaluates_none(),
        nullable=False,
        server_default=text('\'{"mode":"all","document_ids":[]}\''),
    )
    scope_revision: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    next_message_seq: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("1")
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="RESTRICT"),
        CheckConstraint("sequence_no > 0"),
        CheckConstraint("role IN ('user', 'assistant')"),
        CheckConstraint(
            "status IN ('queued', 'retrieving', 'generating', 'completed', 'stopped', 'failed')"
        ),
        CheckConstraint("answer_kind IN ('answered', 'partially_answered', 'refused')"),
        CheckConstraint("jsonb_typeof(request_snapshot) = 'object'"),
        CheckConstraint("jsonb_typeof(error) = 'object'"),
        CheckConstraint("jsonb_typeof(usage) = 'object'"),
        UniqueConstraint("session_id", "sequence_no"),
        UniqueConstraint("session_id", "client_request_id"),
        UniqueConstraint("reply_to_message_id"),
        UniqueConstraint("id", "session_id"),
        ForeignKeyConstraint(
            ["reply_to_message_id", "session_id"],
            ["chat_messages.id", "chat_messages.session_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(role = 'user' AND status = 'completed' AND reply_to_message_id IS NULL AND "
            "client_request_id IS NULL AND request_snapshot IS NULL AND answer_kind IS "
            "NULL) OR (role = 'assistant' AND reply_to_message_id IS NOT NULL AND "
            "reply_to_message_id <> id AND client_request_id IS NOT NULL AND "
            "request_snapshot IS NOT NULL)"
        ),
        CheckConstraint("role <> 'assistant' OR status <> 'completed' OR answer_kind IS NOT NULL"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, nullable=False)
    session_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    sequence_no: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    reply_to_message_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    client_request_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'completed'"))
    answer_kind: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_snapshot: Mapped[dict | None] = mapped_column(
        JSONB(none_as_null=True).evaluates_none(), nullable=True
    )
    error: Mapped[dict | None] = mapped_column(
        JSONB(none_as_null=True).evaluates_none(), nullable=True
    )
    usage: Mapped[dict | None] = mapped_column(
        JSONB(none_as_null=True).evaluates_none(), nullable=True
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    stop_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class MessageCitation(Base):
    __tablename__ = "message_citations"
    __table_args__ = (
        ForeignKeyConstraint(["message_id"], ["chat_messages.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["chunk_id"], ["chunks.id"], ondelete="RESTRICT"),
        CheckConstraint("citation_no > 0"),
        CheckConstraint("btrim(quote) <> ''"),
        CheckConstraint("jsonb_typeof(source_snapshot) = 'object'"),
        UniqueConstraint("message_id", "citation_no"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, nullable=False)
    message_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    chunk_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    citation_no: Mapped[int] = mapped_column(Integer, nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    source_snapshot: Mapped[dict] = mapped_column(
        JSONB(none_as_null=True).evaluates_none(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


Index(
    "ix_documents_recent",
    Document.updated_at.desc(),
    Document.id.desc(),
    postgresql_where=text("deleted_at IS NULL"),
)

Index(
    "ix_documents_category",
    Document.category,
    Document.updated_at.desc(),
    Document.id.desc(),
    postgresql_where=text("deleted_at IS NULL"),
)

Index(
    "ux_import_active",
    ProcessingJob.version_id,
    unique=True,
    postgresql_where=text("job_type = 'import' AND status IN ('queued', 'running')"),
)

Index(
    "ux_graph_active",
    ProcessingJob.source_job_id,
    unique=True,
    postgresql_where=text("job_type = 'graph' AND status IN ('queued', 'running')"),
)

Index(
    "ix_jobs_dispatch",
    ProcessingJob.next_dispatch_at,
    ProcessingJob.id,
    postgresql_where=text("status = 'queued'"),
)

Index("ix_jobs_lease", ProcessingJob.lease_expires_at, postgresql_where=text("status = 'running'"))

Index(
    "ix_jobs_latest_ready_graph",
    ProcessingJob.source_job_id,
    ProcessingJob.generation_no.desc(),
    postgresql_where=text("job_type = 'graph' AND status = 'ready'"),
)

Index(
    "ix_sessions_recent",
    ChatSession.last_message_at.desc().nulls_last(),
    ChatSession.id.desc(),
    postgresql_where=text("deleted_at IS NULL"),
)

Index(
    "ux_session_active_answer",
    ChatMessage.session_id,
    unique=True,
    postgresql_where=text(
        "role = 'assistant' AND status IN ('queued', 'retrieving', 'generating')"
    ),
)

Index(
    "ix_messages_expired",
    ChatMessage.lease_expires_at,
    postgresql_where=text(
        "role = 'assistant' AND status IN ('queued', 'retrieving', 'generating')"
    ),
)

Index("ix_citations_chunk", MessageCitation.chunk_id)
