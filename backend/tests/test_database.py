from uuid import uuid4

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.integration


def test_schema_has_eight_core_tables_and_vector_extension(test_engine):
    assert set(inspect(test_engine).get_table_names()) - {"alembic_version"} == {
        "documents",
        "document_versions",
        "document_contents",
        "chunks",
        "processing_jobs",
        "chat_sessions",
        "chat_messages",
        "message_citations",
    }
    with test_engine.connect() as conn:
        assert conn.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))


def test_original_file_deduplication_is_per_document(db, source):
    from app.models import Document, DocumentVersion

    document, version, *_ = source
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(
            DocumentVersion(
                id=uuid4(),
                document_id=document.id,
                version_no=2,
                original_filename="再次上传.pdf",
                format="pdf",
                size_bytes=100,
                file_sha256="a" * 64,
                file_ref={},
            )
        )
        db.flush()
    other = Document(id=uuid4(), title="另一逻辑文档")
    db.add(other)
    db.flush()
    db.add(
        DocumentVersion(
            id=uuid4(),
            document_id=other.id,
            version_no=1,
            original_filename="重复字节.pdf",
            format="pdf",
            size_bytes=100,
            file_sha256="a" * 64,
            file_ref={},
        )
    )
    db.flush()


def test_current_version_cannot_point_at_another_document(db, source):
    from app.models import Document

    _, version, *_ = source
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(Document(id=uuid4(), title="错误指针", current_version_id=version.id))
        db.flush()


def test_one_active_import_per_version(db, source):
    from app.models import ProcessingJob

    _, version, *_ = source
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(
            ProcessingJob(
                id=uuid4(),
                version_id=version.id,
                generation_no=2,
                job_type="import",
                config={},
                config_hash="a" * 64,
                embedding_profile_hash="c" * 64,
                embedding_dimension=3,
            )
        )
        db.flush()


@pytest.mark.parametrize(
    "changes",
    [
        {"embedding_dimension": 2},
        {"embedding_profile_hash": "f" * 64},
        {"page_start": 0},
        {"page_end": None},
        {"ordinal": -1},
    ],
)
def test_chunk_rejects_mismatched_index_and_invalid_location(db, source, changes):
    _, _, _, chunk = source
    with pytest.raises(IntegrityError), db.begin_nested():
        for key, value in changes.items():
            setattr(chunk, key, value)
        db.flush()


def test_vector_dimensions_are_enforced(db, source):
    *_, chunk = source
    with pytest.raises(IntegrityError), db.begin_nested():
        chunk.embedding = [1, 0]
        db.flush()


def test_failed_transaction_does_not_leave_document(db):
    from app.models import Document

    document_id = uuid4()
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add_all([Document(id=document_id, title="应回滚"), Document(id=uuid4(), title=" ")])
        db.flush()
    assert db.get(Document, document_id) is None


def test_document_directory_does_not_load_body_blocks_or_vectors(db, source):
    from app.models import Document

    db.expire_all()
    rows = db.scalars(select(Document)).all()
    assert rows[0].title == "费用报销管理制度"
    assert not {"markdown", "blocks", "embedding"}.intersection(inspect(rows[0]).attrs.keys())


@pytest.mark.parametrize("scope", [None, [], {"mode": None, "document_ids": []}])
def test_scope_malformed_shapes_are_rejected_by_database(db, scope):
    from app.models import ChatSession

    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(ChatSession(id=uuid4(), scope=scope))
        db.flush()
