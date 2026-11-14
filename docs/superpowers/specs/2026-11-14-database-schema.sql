-- 企业知识助理：8 张核心表的评审用 DDL，2026-11-14。
-- 这是设计附件，尚未作为 Alembic 迁移执行。
-- PostgreSQL 16 + pgvector；模型配置/维度在联调后锁定，不预建定维 ANN 索引。
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
    id uuid PRIMARY KEY,
    title varchar(300) NOT NULL CHECK (btrim(title) <> ''),
    category varchar(80) NOT NULL DEFAULT '未分类' CHECK (btrim(category) <> ''),
    current_version_id uuid,
    next_version_no integer NOT NULL DEFAULT 1 CHECK (next_version_no > 0),
    revision bigint NOT NULL DEFAULT 0 CHECK (revision >= 0),
    deleted_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE document_versions (
    id uuid PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES documents(id) ON DELETE RESTRICT,
    version_no integer NOT NULL CHECK (version_no > 0),
    version_label varchar(80),
    original_filename varchar(500) NOT NULL,
    format text NOT NULL CHECK (format IN ('pdf','docx','md')),
    size_bytes bigint NOT NULL CHECK (size_bytes > 0),
    file_sha256 char(64) NOT NULL CHECK (file_sha256 ~ '^[0-9a-f]{64}$'),
    file_ref jsonb NOT NULL CHECK (jsonb_typeof(file_ref) = 'object'),
    source_metadata jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(source_metadata) = 'object'),
    active_import_job_id uuid,
    next_generation_no integer NOT NULL DEFAULT 1 CHECK (next_generation_no > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, version_no),
    UNIQUE (document_id, file_sha256),
    UNIQUE (id, document_id)
);

CREATE TABLE processing_jobs (
    id uuid PRIMARY KEY,
    version_id uuid NOT NULL REFERENCES document_versions(id) ON DELETE RESTRICT,
    job_type text NOT NULL CHECK (job_type IN ('import','graph')),
    source_job_id uuid,
    generation_no integer NOT NULL CHECK (generation_no > 0),
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','running','ready','failed','canceled')),
    stage text NOT NULL DEFAULT 'queued'
        CHECK (stage IN ('queued','parsing','chunking','embedding','publishing',
                         'extracting','validating','projecting','done')),
    config jsonb NOT NULL CHECK (jsonb_typeof(config) = 'object'),
    config_hash char(64) NOT NULL CHECK (config_hash ~ '^[0-9a-f]{64}$'),
    embedding_profile_hash char(64),
    embedding_dimension smallint,
    checkpoint jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(checkpoint) = 'object'),
    attempt_no integer NOT NULL DEFAULT 0 CHECK (attempt_no >= 0),
    max_attempts smallint NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
    lease_owner varchar(120),
    lease_token bigint NOT NULL DEFAULT 0 CHECK (lease_token >= 0),
    lease_expires_at timestamptz,
    next_dispatch_at timestamptz NOT NULL DEFAULT now(),
    last_dispatched_at timestamptz,
    dispatch_attempts integer NOT NULL DEFAULT 0 CHECK (dispatch_attempts >= 0),
    error jsonb CHECK (jsonb_typeof(error) = 'object'),
    started_at timestamptz,
    finished_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (version_id, generation_no),
    UNIQUE (id, version_id),
    UNIQUE (id, version_id, embedding_profile_hash, embedding_dimension),
    FOREIGN KEY (source_job_id, version_id)
        REFERENCES processing_jobs(id, version_id) ON DELETE RESTRICT,
    CHECK ((lease_owner IS NULL) = (lease_expires_at IS NULL)),
    CHECK (source_job_id IS NULL OR source_job_id <> id),
    CHECK (
        (job_type = 'import' AND source_job_id IS NULL
         AND embedding_profile_hash IS NOT NULL
         AND embedding_profile_hash ~ '^[0-9a-f]{64}$'
         AND embedding_dimension IS NOT NULL AND embedding_dimension > 0)
        OR
        (job_type = 'graph' AND source_job_id IS NOT NULL
         AND embedding_profile_hash IS NULL AND embedding_dimension IS NULL)
    ),
    CHECK (
        stage IN ('queued','done')
        OR (job_type = 'import' AND stage IN ('parsing','chunking','embedding','publishing'))
        OR (job_type = 'graph' AND stage IN ('extracting','validating','projecting'))
    ),
    CHECK (status <> 'ready' OR (stage = 'done' AND finished_at IS NOT NULL))
);

ALTER TABLE documents ADD CONSTRAINT fk_documents_current_version
    FOREIGN KEY (current_version_id, id)
    REFERENCES document_versions(id, document_id) ON DELETE RESTRICT;
ALTER TABLE document_versions ADD CONSTRAINT fk_versions_active_import
    FOREIGN KEY (active_import_job_id, id)
    REFERENCES processing_jobs(id, version_id) ON DELETE RESTRICT;

CREATE TABLE document_contents (
    job_id uuid PRIMARY KEY,
    version_id uuid NOT NULL,
    markdown text NOT NULL,
    blocks jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(blocks) = 'array'),
    artifacts jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(artifacts) = 'object'),
    page_count integer CHECK (page_count > 0),
    content_sha256 char(64) NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (job_id, version_id)
        REFERENCES processing_jobs(id, version_id) ON DELETE RESTRICT
);

CREATE TABLE chunks (
    id uuid PRIMARY KEY,
    job_id uuid NOT NULL,
    version_id uuid NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    content text NOT NULL CHECK (btrim(content) <> ''),
    content_sha256 char(64) NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    heading_path text[] NOT NULL DEFAULT '{}',
    page_start integer,
    page_end integer,
    locators jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(locators) = 'array'),
    embedding_profile_hash char(64) NOT NULL,
    embedding_dimension smallint NOT NULL CHECK (embedding_dimension > 0),
    embedding vector,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (job_id, ordinal),
    FOREIGN KEY (job_id, version_id, embedding_profile_hash, embedding_dimension)
        REFERENCES processing_jobs(id, version_id, embedding_profile_hash, embedding_dimension)
        ON DELETE RESTRICT,
    CHECK ((page_start IS NULL AND page_end IS NULL)
        OR (page_start IS NOT NULL AND page_end IS NOT NULL
            AND page_start >= 1 AND page_end >= page_start)),
    CHECK (embedding IS NULL OR vector_dims(embedding) = embedding_dimension)
);

CREATE TABLE chat_sessions (
    id uuid PRIMARY KEY,
    title varchar(300) NOT NULL DEFAULT '新会话' CHECK (btrim(title) <> ''),
    scope jsonb NOT NULL DEFAULT '{"mode":"all","document_ids":[]}'
        CHECK (jsonb_typeof(scope) = 'object'
            AND scope ? 'mode' AND scope ? 'document_ids'
            AND scope->>'mode' IS NOT NULL AND scope->>'mode' IN ('all','custom')
            AND jsonb_typeof(scope->'document_ids') = 'array'),
    scope_revision bigint NOT NULL DEFAULT 0 CHECK (scope_revision >= 0),
    next_message_seq bigint NOT NULL DEFAULT 1 CHECK (next_message_seq > 0),
    last_message_at timestamptz,
    deleted_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE chat_messages (
    id uuid PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES chat_sessions(id) ON DELETE RESTRICT,
    sequence_no bigint NOT NULL CHECK (sequence_no > 0),
    role text NOT NULL CHECK (role IN ('user','assistant')),
    reply_to_message_id uuid,
    client_request_id uuid,
    content text NOT NULL DEFAULT '',
    status text NOT NULL DEFAULT 'completed'
        CHECK (status IN ('queued','retrieving','generating','completed','stopped','failed')),
    answer_kind text CHECK (answer_kind IN ('answered','partially_answered','refused')),
    request_snapshot jsonb CHECK (jsonb_typeof(request_snapshot) = 'object'),
    error jsonb CHECK (jsonb_typeof(error) = 'object'),
    usage jsonb CHECK (jsonb_typeof(usage) = 'object'),
    lease_expires_at timestamptz,
    stop_requested_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (session_id, sequence_no),
    UNIQUE (session_id, client_request_id),
    UNIQUE (reply_to_message_id),
    UNIQUE (id, session_id),
    FOREIGN KEY (reply_to_message_id, session_id)
        REFERENCES chat_messages(id, session_id) ON DELETE RESTRICT,
    CHECK (
        (role = 'user' AND status = 'completed'
         AND reply_to_message_id IS NULL AND client_request_id IS NULL
         AND request_snapshot IS NULL AND answer_kind IS NULL)
        OR
        (role = 'assistant' AND reply_to_message_id IS NOT NULL
         AND reply_to_message_id <> id AND client_request_id IS NOT NULL
         AND request_snapshot IS NOT NULL)
    ),
    CHECK (role <> 'assistant' OR status <> 'completed' OR answer_kind IS NOT NULL)
);

CREATE TABLE message_citations (
    id uuid PRIMARY KEY,
    message_id uuid NOT NULL REFERENCES chat_messages(id) ON DELETE RESTRICT,
    chunk_id uuid NOT NULL REFERENCES chunks(id) ON DELETE RESTRICT,
    citation_no integer NOT NULL CHECK (citation_no > 0),
    quote text NOT NULL CHECK (btrim(quote) <> ''),
    source_snapshot jsonb NOT NULL CHECK (jsonb_typeof(source_snapshot) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (message_id, citation_no)
);

CREATE INDEX ix_documents_recent ON documents (updated_at DESC, id DESC)
    WHERE deleted_at IS NULL;
CREATE INDEX ix_documents_category ON documents (category, updated_at DESC, id DESC)
    WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX ux_import_active ON processing_jobs (version_id)
    WHERE job_type = 'import' AND status IN ('queued','running');
CREATE UNIQUE INDEX ux_graph_active ON processing_jobs (source_job_id)
    WHERE job_type = 'graph' AND status IN ('queued','running');
CREATE INDEX ix_jobs_dispatch ON processing_jobs (next_dispatch_at, id)
    WHERE status = 'queued';
CREATE INDEX ix_jobs_lease ON processing_jobs (lease_expires_at)
    WHERE status = 'running';
CREATE INDEX ix_jobs_latest_ready_graph ON processing_jobs (source_job_id, generation_no DESC)
    WHERE job_type = 'graph' AND status = 'ready';
CREATE INDEX ix_sessions_recent ON chat_sessions (last_message_at DESC NULLS LAST, id DESC)
    WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX ux_session_active_answer ON chat_messages (session_id)
    WHERE role = 'assistant' AND status IN ('queued','retrieving','generating');
CREATE INDEX ix_messages_expired ON chat_messages (lease_expires_at)
    WHERE role = 'assistant' AND status IN ('queued','retrieving','generating');
CREATE INDEX ix_citations_chunk ON message_citations (chunk_id);
