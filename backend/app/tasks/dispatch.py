from datetime import UTC, datetime, timedelta

from sqlalchemy import null, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import create_db_engine
from app.importing.storage import ObjectStorage
from app.models import DocumentContent, DocumentVersion, ProcessingJob


def publish(settings: Settings, job_id):
    from app.tasks.celery_app import create_celery

    engine = create_db_engine(settings)
    try:
        with Session(engine) as db:
            kind = db.scalar(select(ProcessingJob.job_type).where(ProcessingJob.id == job_id))
    finally:
        engine.dispose()
    with create_celery(settings) as broker:
        broker.send_task(
            "graph.process" if kind == "graph" else "documents.process",
            args=[str(job_id)],
            queue="documents",
            retry=False,
        )


def dispatch_pending(settings: Settings, *, job_ids=None, publisher=None) -> int:
    """Commit the next dispatch time before sending; a crash leaves a recoverable row."""
    engine = create_db_engine(settings)
    try:
        now = datetime.now(UTC)
        with Session(engine) as db, db.begin():
            query = select(ProcessingJob).where(
                ProcessingJob.status == "queued",
                ProcessingJob.next_dispatch_at <= now,
            )
            if job_ids is not None:
                query = query.where(ProcessingJob.id.in_(job_ids))
            jobs = list(
                db.scalars(
                    query.order_by(ProcessingJob.next_dispatch_at)
                    .limit(100)
                    .with_for_update(skip_locked=True)
                )
            )
            selected = []
            for job in jobs:
                job.dispatch_attempts += 1
                job.next_dispatch_at = now + timedelta(
                    seconds=min(
                        300, settings.dispatch_interval * 2 ** min(job.dispatch_attempts - 1, 5)
                    )
                )
                selected.append(job.id)
        sent = 0
        for identity in selected:
            error = None
            try:
                (publisher or (lambda value: publish(settings, value)))(identity)
                sent += 1
            except Exception:
                error = {
                    "code": "queue_unavailable",
                    "message": "任务已保存，等待队列恢复",
                    "retryable": True,
                    "stage": "queued",
                }
            with Session(engine) as db, db.begin():
                if error is None:
                    # A fast worker may already have finished. Preserve its error, but
                    # still record that the broker accepted this dispatch.
                    db.execute(
                        update(ProcessingJob)
                        .where(ProcessingJob.id == identity)
                        .values(last_dispatched_at=datetime.now(UTC))
                    )
                values = {"error": error} if error else {"error": null()}
                db.execute(
                    update(ProcessingJob)
                    .where(ProcessingJob.id == identity, ProcessingJob.status == "queued")
                    .values(**values)
                )
        return sent
    finally:
        engine.dispose()


def recover_expired(settings: Settings) -> int:
    engine = create_db_engine(settings)
    try:
        with Session(engine) as db, db.begin():
            now = datetime.now(UTC)
            jobs = list(
                db.scalars(
                    select(ProcessingJob)
                    .where(
                        ProcessingJob.status == "running",
                        ProcessingJob.lease_expires_at < now,
                    )
                    .with_for_update(skip_locked=True)
                )
            )
            for job in jobs:
                job.lease_token += 1
                job.lease_owner = job.lease_expires_at = None
                if job.attempt_no >= job.max_attempts:
                    job.status, job.finished_at = "failed", now
                    job.error = {
                        "code": "lease_exhausted",
                        "message": "处理多次中断，已达到重试上限",
                        "retryable": False,
                        "stage": job.stage,
                    }
                else:
                    job.status, job.stage, job.next_dispatch_at = "queued", "queued", now
            return len(jobs)
    finally:
        engine.dispose()


def cleanup_orphans(settings: Settings, *, cutoff=None) -> int:
    """Remove old unreferenced objects only inside this project's configured prefixes."""
    cutoff = cutoff or datetime.now(UTC) - timedelta(hours=24)
    storage = ObjectStorage(settings)
    engine = create_db_engine(settings)
    removed = 0
    try:
        with Session(engine) as db:
            for item in storage.list_originals():
                if item["modified_at"] >= cutoff:
                    continue
                referenced = db.scalar(
                    select(DocumentVersion.id)
                    .where(DocumentVersion.file_ref["object_key"].astext == item["key"])
                    .limit(1)
                )
                if referenced is None:
                    storage.delete(item["key"])
                    removed += 1
            referenced_keys = set()
            for manifest in db.scalars(select(DocumentContent.artifacts)):
                candidates = [manifest.get("archive", {}), *manifest.get("assets", {}).values()]
                referenced_keys.update(a["object_key"] for a in candidates if a.get("object_key"))
            active_ids = {
                str(identity)
                for identity in db.scalars(
                    select(ProcessingJob.id).where(
                        ProcessingJob.status.in_(["queued", "running"]),
                    )
                )
            }
            prefix = settings.parsed_prefix.rstrip("/") + "/"
            for item in storage.list_objects(settings.parsed_prefix):
                job_id = item["key"][len(prefix) :].split("/", 1)[0]
                if (
                    item["modified_at"] >= cutoff
                    or item["key"] in referenced_keys
                    or job_id in active_ids
                ):
                    continue
                storage.delete(item["key"])
                removed += 1
        return removed
    finally:
        engine.dispose()
