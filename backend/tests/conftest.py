from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


@pytest.fixture(scope="session")
def test_engine():
    """Use a separate database on this project's server; never drop the app database."""
    from app.config import Settings
    from app.db import create_db_engine

    settings = Settings()
    url = make_url(settings.database_url.get_secret_value())
    assert url.database == "knowledge_assistant", (
        "Integration tests require this project's database"
    )
    target = url.set(database="knowledge_assistant_test")
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        if not conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname='knowledge_assistant_test'")
        ):
            conn.exec_driver_sql("CREATE DATABASE knowledge_assistant_test")
    admin.dispose()
    test_settings = settings.model_copy(
        update={
            "database_url": settings.database_url.__class__(
                target.render_as_string(hide_password=False)
            )
        }
    )
    engine = create_db_engine(test_settings)
    from alembic import command
    from alembic.config import Config

    from app.config import PROJECT_ROOT

    migration = Config(str(PROJECT_ROOT / "backend/alembic.ini"))
    with engine.begin() as conn:
        migration.attributes["connection"] = conn
        command.upgrade(migration, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def db(test_engine):
    with test_engine.connect() as conn:
        txn = conn.begin()
        with Session(bind=conn, join_transaction_mode="create_savepoint") as session:
            yield session
        txn.rollback()


@pytest.fixture
def source(db):
    from app.models import Chunk, Document, DocumentContent, DocumentVersion, ProcessingJob

    document = Document(id=uuid4(), title="费用报销管理制度", category="财务制度")
    db.add(document)
    db.flush()
    version = DocumentVersion(
        id=uuid4(),
        document_id=document.id,
        version_no=1,
        version_label="1.1",
        original_filename="费用制度.pdf",
        format="pdf",
        size_bytes=100,
        file_sha256="a" * 64,
        file_ref={"bucket": "knowledge-assistant", "object_key": "test/raw.pdf"},
    )
    db.add(version)
    db.flush()
    job = ProcessingJob(
        id=uuid4(),
        version_id=version.id,
        generation_no=1,
        job_type="import",
        config={"schema_version": 1},
        config_hash="b" * 64,
        embedding_profile_hash="c" * 64,
        embedding_dimension=3,
    )
    db.add(job)
    db.flush()
    content = DocumentContent(
        job_id=job.id,
        version_id=version.id,
        markdown="电子发票应提交原始 PDF 文件。",
        blocks=[
            {
                "block_id": "p1",
                "type": "paragraph",
                "text": "电子发票应提交原始 PDF 文件。",
                "heading_path": ["票据要求"],
                "page_start": 1,
                "page_end": 1,
            }
        ],
        content_sha256="d" * 64,
        page_count=4,
    )
    chunk = Chunk(
        id=uuid4(),
        job_id=job.id,
        version_id=version.id,
        ordinal=0,
        content="电子发票应提交原始 PDF 文件。",
        content_sha256="e" * 64,
        heading_path=["票据要求"],
        page_start=1,
        page_end=1,
        locators=[{"block_id": "p1", "page_start": 1, "page_end": 1}],
        embedding_profile_hash="c" * 64,
        embedding_dimension=3,
        embedding=[1, 0, 0],
    )
    db.add_all([content, chunk])
    db.flush()
    return document, version, job, chunk
