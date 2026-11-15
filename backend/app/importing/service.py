from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.importing.fingerprints import file_fingerprint, lock_and_check_file
from app.importing.storage import ObjectStorage
from app.importing.validation import validate_file
from app.models import Document, DocumentVersion, ProcessingJob
from app.retrieval.profile import INDEX_OPTIONS, digest_profile, embedding_profile


class ImportProblem(ValueError):
    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


class ImportAccepted(BaseModel):
    document_id: UUID
    version_id: UUID
    job_id: UUID | None
    duplicate: bool


def new_import_job(
    settings: Settings,
    version: DocumentVersion,
    identity: UUID,
    generation: int,
    *,
    operation="upload",
    source_content_job_id=None,
):
    profile = embedding_profile(settings)
    config = {
        "schema_version": 3,
        "operation": operation,
        "source_content_job_id": str(source_content_job_id) if source_content_job_id else None,
        "parser": {
            "provider": "markdown" if version.format == "md" else "mineru",
            "model": settings.mineru_model,
            "language": settings.mineru_language,
            "normalizer_version": 1,
        },
        "embedding": profile,
        "indexing": {
            **INDEX_OPTIONS,
            "batch_size": settings.embedding_batch_size,
            "enabled": settings.embedding_model not in {"", "not-configured"},
        },
    }

    return ProcessingJob(
        id=identity,
        version_id=version.id,
        generation_no=generation,
        job_type="import",
        config=config,
        config_hash=digest_profile(config),
        embedding_profile_hash=digest_profile(profile),
        embedding_dimension=settings.embedding_dimension,
        max_attempts=settings.import_max_attempts,
    )


class ImportService:
    """Caller owns the transaction; no broker calls happen before its commit."""

    def __init__(self, db: Session, settings: Settings, storage: ObjectStorage):
        self.db, self.settings, self.storage = db, settings, storage

    def _existing(self, version_id: UUID) -> ImportAccepted:
        version = self.db.get(DocumentVersion, version_id)
        job_id = self.db.scalar(
            select(ProcessingJob.id)
            .where(ProcessingJob.version_id == version_id, ProcessingJob.job_type == "import")
            .order_by(ProcessingJob.generation_no.desc())
            .limit(1)
        )
        return ImportAccepted(
            document_id=version.document_id, version_id=version_id, job_id=job_id, duplicate=True
        )

    def create(
        self,
        document_id: UUID,
        filename: str,
        content: bytes,
        title: str | None = None,
        category: str = "未分类",
    ) -> ImportAccepted:
        return self._accept(document_id, filename, content, title, category, new_version=False)

    def add_version(self, document_id: UUID, filename: str, content: bytes) -> ImportAccepted:
        return self._accept(document_id, filename, content, None, "未分类", new_version=True)

    def _accept(self, document_id, filename, content, title, category, *, new_version):
        validated = validate_file(filename, content, max_bytes=self.settings.upload_max_bytes)
        sha256 = file_fingerprint(content)
        # The two-key namespace is distinct from the one-key file fingerprint locks.
        key = int.from_bytes(document_id.bytes[:4], "big", signed=True)
        self.db.execute(text("SELECT pg_advisory_xact_lock(22014, :key)"), {"key": key})
        document = self.db.scalar(
            select(Document).where(Document.id == document_id).with_for_update()
        )
        if new_version and (document is None or document.deleted_at is not None):
            raise ImportProblem("文档不存在或已移除", 404)
        if document is not None and not new_version:
            existing = self.db.scalar(
                select(DocumentVersion.id).where(
                    DocumentVersion.document_id == document_id,
                    DocumentVersion.file_sha256 == sha256,
                )
            )
            if document.deleted_at is not None or existing is None:
                raise ImportProblem("该上传标识已用于另一文件，请使用上传新版本")
        match = lock_and_check_file(self.db, content)
        if match.duplicate:
            return self._existing(match.existing.version_id)
        if document is None:
            actual_title = (title or validated.filename.rsplit(".", 1)[0]).strip()
            if (
                not actual_title
                or len(actual_title) > 300
                or not category.strip()
                or len(category) > 80
            ):
                raise ImportProblem("标题或分类无效", 422)
            document = Document(id=document_id, title=actual_title, category=category.strip())
            self.db.add(document)
            self.db.flush()
        number = max(
            document.next_version_no,
            1
            + (
                self.db.scalar(
                    select(func.max(DocumentVersion.version_no)).where(
                        DocumentVersion.document_id == document_id
                    )
                )
                or 0
            ),
        )
        version_id, job_id = uuid4(), uuid4()
        object_key = (
            f"{self.settings.original_prefix.rstrip('/')}/{version_id}/{validated.filename}"
        )
        self.storage.put(object_key, content, validated.mime_type, sha256)
        version = DocumentVersion(
            id=version_id,
            document_id=document_id,
            version_no=number,
            original_filename=validated.filename,
            format=validated.format,
            size_bytes=len(content),
            file_sha256=sha256,
            next_generation_no=2,
            file_ref={
                "bucket": self.settings.s3_bucket,
                "object_key": object_key,
                "mime_type": validated.mime_type,
            },
        )
        self.db.add(version)
        self.db.flush()
        self.db.add(new_import_job(self.settings, version, job_id, 1))
        document.next_version_no = number + 1
        self.db.flush()
        return ImportAccepted(
            document_id=document_id, version_id=version_id, job_id=job_id, duplicate=False
        )
