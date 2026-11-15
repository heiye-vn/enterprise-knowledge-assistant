import io
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from botocore.exceptions import BotoCoreError, ClientError
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import null, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import create_db_engine
from app.importing.archive import read_archive
from app.importing.fingerprints import file_fingerprint
from app.importing.mineru import MinerUClient
from app.importing.parsing import ParseError, content_hash, parse_markdown
from app.importing.storage import ObjectStorage
from app.model_clients import ModelProblem
from app.models import DocumentContent, DocumentVersion, ProcessingJob
from app.retrieval.chunking import ChunkingProblem


class LostLease(Exception):
    pass


def claim_job(settings: Settings, identity: UUID) -> int | None:
    engine = create_db_engine(settings)
    try:
        with Session(engine) as db, db.begin():
            job = db.scalar(
                select(ProcessingJob)
                .where(ProcessingJob.id == identity, ProcessingJob.job_type == "import")
                .with_for_update()
            )
            if job is None or job.status != "queued":
                return None
            now = datetime.now(UTC)
            cp = dict(job.checkpoint)
            continuation = cp.get("continue", False)
            if continuation and datetime.fromisoformat(cp["resume_at"]) > now:
                return None
            if not continuation and job.attempt_no >= job.max_attempts:
                return None
            cp.pop("continue", None)
            cp.pop("resume_at", None)
            job.checkpoint = cp
            phase = (
                "embedding"
                if cp.get("indexing", {}).get("prepared")
                else ("chunking" if cp.get("parsed_saved") else "parsing")
            )
            job.status, job.stage = "running", phase
            if not continuation:
                job.attempt_no += 1
            job.lease_token += 1
            job.lease_owner = str(uuid4())
            job.lease_expires_at = now + timedelta(seconds=settings.job_lease_seconds)
            job.started_at, job.finished_at = now, None
            job.error = null()
            return job.lease_token
    finally:
        engine.dispose()


def fail_job(settings: Settings, identity: UUID, token: int, error: dict) -> bool:
    engine = create_db_engine(settings)
    try:
        with Session(engine) as db, db.begin():
            result = db.execute(
                update(ProcessingJob)
                .where(
                    ProcessingJob.id == identity,
                    ProcessingJob.status == "running",
                    ProcessingJob.lease_token == token,
                    ProcessingJob.lease_expires_at > datetime.now(UTC),
                )
                .values(
                    status="failed",
                    error=error,
                    finished_at=datetime.now(UTC),
                    lease_owner=None,
                    lease_expires_at=None,
                )
            )
            return result.rowcount == 1
    finally:
        engine.dispose()


def process_document(job_id: str, settings: Settings | None = None):
    from app.tasks.indexing import IndexingProblem, run_indexing

    settings = settings or Settings()
    identity = UUID(job_id)
    token = claim_job(settings, identity)
    if token is None:
        return
    engine = create_db_engine(settings)
    try:
        with Session(engine) as db:
            job = db.get(ProcessingJob, identity)
            version = db.get(DocumentVersion, job.version_id)
            key, expected = version.file_ref["object_key"], version.file_sha256
            format, filename, version_id = version.format, version.original_filename, version.id
            config, cp = job.config, dict(job.checkpoint)
            saved = db.get(DocumentContent, identity) is not None
        enabled = config.get("indexing", {}).get("enabled", False)
        if saved:
            if enabled:
                run_indexing(engine, settings, identity, token)
                return
            raise ParseError("index_not_configured", "解析完成，尚未配置索引")
        if config.get("source_content_job_id"):
            with Session(engine) as db, db.begin():
                live = live_job(db, identity, token)
                source = db.get(DocumentContent, UUID(config["source_content_job_id"]))
                if source is None or source.version_id != version_id:
                    raise IndexingProblem(
                        "parsed_content_missing", "该版本没有可复用的解析结果，请重新解析"
                    )
                db.add(
                    DocumentContent(
                        job_id=identity,
                        version_id=version_id,
                        markdown=source.markdown,
                        blocks=source.blocks,
                        artifacts=source.artifacts,
                        page_count=source.page_count,
                        content_sha256=source.content_sha256,
                    )
                )
                live.checkpoint = {**live.checkpoint, "parsed_saved": True}
                live.stage = "chunking"
            run_indexing(engine, settings, identity, token)
            return
        storage = ObjectStorage(settings)
        content = storage.read(key)
        if file_fingerprint(content) != expected:
            raise ParseError("original_checksum_mismatch", "原件校验失败，请重新上传")
        if not isinstance(config.get("parser"), dict):
            raise ParseError("parser_not_configured", "该任务使用旧版解析配置，请使用重新解析")
        raw = None
        if format == "md":
            parsed = parse_markdown(content)
        else:
            parser = config["parser"]
            run_settings = settings.model_copy(
                update={
                    "mineru_model": parser["model"],
                    "mineru_language": parser["language"],
                }
            )
            with MinerUClient(run_settings) as mineru:
                raw = cloud_step(engine, identity, token, cp, mineru, filename, content, settings)
            if raw is None:
                return
            parsed = read_archive(raw, format)
            if format == "pdf":
                try:
                    parsed.page_count = len(PdfReader(io.BytesIO(content)).pages)
                except (PdfReadError, ValueError):
                    raise ParseError("invalid_pdf", "无法确认原件 PDF 的真实页数") from None
                if any((b["page_end"] or 0) > parsed.page_count for b in parsed.blocks):
                    raise ParseError("invalid_page_location", "解析页码超出原件范围")
        artifacts = {"assets": {}}
        prefix = f"{settings.parsed_prefix.rstrip('/')}/{identity}/{token}"
        if raw is not None:
            artifacts["archive"] = put_artifact(
                storage, prefix + "/result.zip", raw, "application/zip"
            )
        for asset_id, asset in parsed.assets.items():
            artifacts["assets"][asset_id] = put_artifact(
                storage,
                prefix + "/" + asset_id,
                asset.content,
                asset.mime_type,
            )
        with Session(engine) as db, db.begin():
            live = live_job(db, identity, token)
            db.add(
                DocumentContent(
                    job_id=identity,
                    version_id=version_id,
                    markdown=parsed.markdown,
                    blocks=parsed.blocks,
                    artifacts=artifacts,
                    page_count=parsed.page_count,
                    content_sha256=content_hash(parsed.markdown),
                )
            )
            live.stage = "chunking"
            if not enabled:
                live.status = "failed"
                live.error = {
                    "code": "index_not_configured",
                    "message": "解析完成，尚未配置索引",
                    "retryable": False,
                    "stage": "chunking",
                }
                live.finished_at = datetime.now(UTC)
                live.lease_owner = live.lease_expires_at = None
            # Presigned URLs remain internal only while needed for upload recovery.
            cp = {**live.checkpoint, "parsed_saved": True}
            if "mineru" in cp:
                cp["mineru"] = {
                    k: v for k, v in cp["mineru"].items() if k not in {"upload_url", "archive_url"}
                }
                cp["mineru"]["phase"] = "complete"
            live.checkpoint = cp
        if enabled:
            run_indexing(engine, settings, identity, token)
        return
    except LostLease:
        return
    except ParseError as problem:
        error = {
            "code": problem.code,
            "message": str(problem),
            "retryable": problem.retryable,
            "stage": "parsing",
        }
    except ModelProblem as problem:
        error = {
            "code": problem.code,
            "message": str(problem),
            "retryable": problem.retryable,
            "stage": "embedding",
        }
    except ChunkingProblem as problem:
        error = {
            "code": "invalid_chunks",
            "message": str(problem),
            "retryable": False,
            "stage": "chunking",
        }
    except IndexingProblem as problem:
        error = {
            "code": problem.code,
            "message": str(problem),
            "retryable": problem.retryable,
            "stage": problem.stage,
        }
    except SQLAlchemyError:
        error = {
            "code": "index_storage_unavailable",
            "message": "暂时无法保存索引，可重试处理",
            "retryable": True,
            "stage": "embedding",
        }
    except (BotoCoreError, ClientError, OSError):
        error = {
            "code": "storage_unavailable",
            "message": "暂时无法读取原件，可重试处理",
            "retryable": True,
            "stage": "parsing",
        }
    finally:
        engine.dispose()
    fail_job(settings, identity, token, error)


def live_job(db, identity, token):
    job = db.scalar(
        select(ProcessingJob)
        .where(
            ProcessingJob.id == identity,
            ProcessingJob.status == "running",
            ProcessingJob.lease_token == token,
            ProcessingJob.lease_expires_at > datetime.now(UTC),
        )
        .with_for_update()
    )
    if job is None:
        raise LostLease
    return job


def save_checkpoint(engine, identity, token, cp):
    with Session(engine) as db, db.begin():
        live_job(db, identity, token).checkpoint = dict(cp)


def put_artifact(storage, key, content, mime):
    sha = file_fingerprint(content)
    storage.put(key, content, mime, sha)
    return {"object_key": key, "mime_type": mime, "sha256": sha, "size_bytes": len(content)}


def cloud_step(engine, identity, token, cp, mineru, filename, content, settings):
    remote = dict(cp.get("mineru", {}))
    if remote.get("phase") == "downloading":
        if datetime.fromisoformat(remote["download_deadline"]) < datetime.now(UTC):
            raise ParseError("mineru_download_expired", "解析归档已超过下载期限，请重新解析")
        return mineru.download(remote["archive_url"])
    if remote.get("phase") == "submitting":
        raise ParseError(
            "mineru_submission_unknown", "无法确认此前提交结果，请核对 MinerU 控制台后重新解析"
        )
    if remote and datetime.fromisoformat(remote["deadline"]) < datetime.now(UTC):
        raise ParseError("mineru_deadline", "云端解析超过等待期限，请核对远端任务后重新解析")
    newly_submitted = not remote
    if newly_submitted:
        # Reject missing credentials before creating an ambiguous external intent.
        if not settings.mineru_api_token.get_secret_value():
            raise ParseError("mineru_not_configured", "请先配置 MinerU Token，再重新解析")
        remote = {
            "phase": "submitting",
            "deadline": (
                datetime.now(UTC) + timedelta(seconds=settings.mineru_deadline_seconds)
            ).isoformat(),
        }
        cp["mineru"] = remote
        save_checkpoint(engine, identity, token, cp)
        response = mineru.submit(filename, str(identity))
        remote = {**remote, **response, "phase": "uploading"}
        cp["mineru"] = remote
        save_checkpoint(engine, identity, token, cp)
    result = None
    if remote["phase"] == "uploading":
        if not newly_submitted:
            result = mineru.poll(remote["batch_id"], str(identity))
        if result is None or result["state"] == "waiting-file":
            mineru.upload(remote["upload_url"], content)
        remote = {**remote, "phase": "polling"}
        cp["mineru"] = remote
        save_checkpoint(engine, identity, token, cp)
    result = result or mineru.poll(remote["batch_id"], str(identity))
    if result["state"] == "done":
        remote = {
            **remote,
            "phase": "downloading",
            "archive_url": result.get("full_zip_url", ""),
            "download_deadline": (datetime.now(UTC) + timedelta(hours=24)).isoformat(),
        }
        cp["mineru"] = remote
        save_checkpoint(engine, identity, token, cp)
        return mineru.download(remote["archive_url"])
    # Persist a delayed continuation. Beat sends it; no worker waits for minutes.
    resume = datetime.now(UTC) + timedelta(seconds=settings.mineru_poll_seconds)
    cp = {**cp, "continue": True, "resume_at": resume.isoformat()}
    with Session(engine) as db, db.begin():
        job = live_job(db, identity, token)
        job.checkpoint, job.status, job.stage = cp, "queued", "parsing"
        job.next_dispatch_at = resume
        job.lease_owner = job.lease_expires_at = None
    return None
