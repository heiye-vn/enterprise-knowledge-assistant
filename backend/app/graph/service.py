"""Graph task acceptance and read snapshots for currently published documents."""

from datetime import UTC, datetime
from uuid import uuid4

from neo4j.exceptions import DriverError, Neo4jError
from sqlalchemy import null, select
from sqlalchemy.orm import Session

from app.graph.extraction import identity
from app.graph.store import GraphStore
from app.models import Document, DocumentVersion, ProcessingJob


class GraphProblem(ValueError):
    def __init__(self, code, message, *, retryable=False, status_code=409):
        super().__init__(message)
        self.code, self.retryable, self.status_code = code, retryable, status_code


def graph_profile(settings):
    return {
        "schema_version": 1,
        "extractor_version": 1,
        "provider": settings.llm_provider,
        "model": settings.qwen_llm_model
        if settings.llm_provider == "qwen"
        else settings.monkey_llm_model,
        "batch_size": settings.graph_batch_size,
        "max_units": settings.graph_max_units,
    }


def catalog_rows(db):
    return list(
        db.execute(
            select(Document, DocumentVersion, ProcessingJob)
            .join(DocumentVersion, Document.current_version_id == DocumentVersion.id)
            .join(ProcessingJob, DocumentVersion.active_import_job_id == ProcessingJob.id)
            .where(
                Document.deleted_at.is_(None),
                ProcessingJob.status == "ready",
                ProcessingJob.job_type == "import",
            )
            .order_by(Document.title, Document.id)
        )
    )


def catalog_view(rows):
    return [
        {
            "document_id": str(doc.id),
            "title": doc.title,
            "filename": version.original_filename,
            "version_id": str(version.id),
            "source_job_id": str(job.id),
        }
        for doc, version, job in rows
    ]


def task_view(job, doc, *, previous=None, config_hash=None):
    graph = (job.checkpoint or {}).get("graph", {}) if job else {}
    return {
        "id": str(job.id) if job else None,
        "document_id": str(doc.id),
        "title": doc.title,
        "status": job.status if job else "not_generated",
        "stage": job.stage if job else "queued",
        "attempt_no": job.attempt_no if job else 0,
        "max_attempts": job.max_attempts if job else 3,
        "error": job.error if job else None,
        "processed_units": graph.get("cursor", 0),
        "total_units": graph.get("unit_count", 0),
        "rule_count": len(graph.get("rules", [])),
        "relation_count": sum(len(rule["relations"]) for rule in graph.get("rules", [])),
        "rejected_count": len(graph.get("rejected", [])),
        "unit_limit_reached": graph.get("unit_limit_reached", False),
        "has_previous": previous is not None and (job is None or previous.id != job.id),
        "needs_update": job is None or job.config_hash != config_hash,
        "source_job_id": str(job.source_job_id) if job else None,
    }


class GraphService:
    def __init__(self, engine, settings):
        self.engine, self.settings = engine, settings

    def config(self, catalog):
        return {
            "namespace": self.settings.graph_namespace,
            "profile": graph_profile(self.settings),
            "catalog": catalog,
        }

    def build(self, document_ids=None):
        jobs, created = [], 0
        with Session(self.engine) as db, db.begin():
            rows = catalog_rows(db)
            catalog = catalog_view(rows)
            if document_ids is not None and not set(document_ids) <= {row[0].id for row in rows}:
                raise GraphProblem("graph_source_unavailable", "所选文档尚未就绪或已移除")
            selected = [row for row in rows if document_ids is None or row[0].id in document_ids]
            if not selected:
                raise GraphProblem("graph_source_unavailable", "请先上传文档并等待索引完成")
            config = self.config(catalog)
            fingerprint = identity(config)
            for doc, version, source in selected:
                # Use the same lock order as import acceptance: document, then version.
                locked_doc = db.scalar(
                    select(Document)
                    .where(Document.id == doc.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if locked_doc.deleted_at is not None or locked_doc.current_version_id != version.id:
                    raise GraphProblem("graph_source_changed", "文档刚刚更新，请刷新后生成图谱")
                version = db.scalar(
                    select(DocumentVersion)
                    .where(DocumentVersion.id == version.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if version.active_import_job_id != source.id:
                    raise GraphProblem("graph_source_changed", "文档刚刚更新，请刷新后生成图谱")
                candidates = list(
                    db.scalars(
                        select(ProcessingJob)
                        .where(
                            ProcessingJob.source_job_id == source.id,
                            ProcessingJob.job_type == "graph",
                            ProcessingJob.config["namespace"].astext
                            == self.settings.graph_namespace,
                        )
                        .order_by(ProcessingJob.generation_no.desc())
                    )
                )
                active = next(
                    (job for job in candidates if job.status in {"queued", "running"}), None
                )
                existing = next((job for job in candidates if job.config_hash == fingerprint), None)
                if active:
                    job = active
                elif existing and existing.status == "ready":
                    job = existing
                elif existing and existing.status == "failed":
                    job = existing
                    if (job.error or {}).get("retryable") and job.attempt_no < job.max_attempts:
                        if (job.error or {}).get("code") == "graph_all_rejected":
                            job.checkpoint = {}
                        job.status, job.stage = "queued", "queued"
                        job.error, job.finished_at = null(), None
                        job.lease_owner = job.lease_expires_at = None
                        job.next_dispatch_at = datetime.now(UTC)
                else:
                    reuse = next(
                        (
                            job
                            for job in candidates
                            if job.config.get("profile") == config["profile"]
                            and (job.checkpoint or {}).get("graph", {}).get("extraction_complete")
                        ),
                        None,
                    )
                    checkpoint = {}
                    if reuse:
                        checkpoint = {
                            "graph": {
                                key: value
                                for key, value in reuse.checkpoint["graph"].items()
                                if key not in {"projection_id", "projection_counts"}
                            }
                        }
                    job = ProcessingJob(
                        id=uuid4(),
                        version_id=version.id,
                        job_type="graph",
                        source_job_id=source.id,
                        generation_no=version.next_generation_no,
                        status="queued",
                        stage="queued",
                        config=config,
                        config_hash=fingerprint,
                        checkpoint=checkpoint,
                        max_attempts=3,
                    )
                    version.next_generation_no += 1
                    db.add(job)
                    created += 1
                db.flush()
                jobs.append(task_view(job, doc, config_hash=fingerprint))
        return {"jobs": jobs, "created": created}

    def read(self, document_id=None):
        projections, evidence, roots, jobs = [], {}, [], []
        with Session(self.engine) as db:
            all_rows = catalog_rows(db)
            config_hash = identity(self.config(catalog_view(all_rows)))
            rows = [row for row in all_rows if document_id is None or row[0].id == document_id]
            for doc, version, source in rows:
                candidates = list(
                    db.scalars(
                        select(ProcessingJob)
                        .where(
                            ProcessingJob.source_job_id == source.id,
                            ProcessingJob.job_type == "graph",
                            ProcessingJob.config["namespace"].astext
                            == self.settings.graph_namespace,
                        )
                        .order_by(ProcessingJob.generation_no.desc())
                    )
                )
                published = next(
                    (
                        job
                        for job in candidates
                        if job.status == "ready"
                        and job.checkpoint.get("graph", {}).get("projection_id")
                    ),
                    None,
                )
                jobs.append(
                    task_view(
                        candidates[0] if candidates else None,
                        doc,
                        previous=published,
                        config_hash=config_hash,
                    )
                )
                if not published:
                    continue
                graph = published.checkpoint["graph"]
                pid = graph["projection_id"]
                projections.append(pid)
                roots.append("document:" + str(doc.id))
                for rule in graph.get("rules", []):
                    eid = identity([pid, rule["unit_id"]])
                    evidence[eid] = {
                        "source": rule["source"],
                        "quote": rule["quote"],
                        "scope": rule["scope"],
                        "conditions": rule["conditions"],
                    }
        result = {
            "nodes": [],
            "edges": [],
            "root_ids": roots,
            "sources": evidence,
            "jobs": jobs,
            "available": True,
            "error": None,
            "truncated": False,
            "fingerprint": identity(["graph-view-v1", projections]),
        }
        try:
            nodes, edges, truncated = GraphStore(self.settings).read(projections)
        except (DriverError, Neo4jError):
            return {
                **result,
                "available": False,
                "error": {
                    "code": "graph_unavailable",
                    "message": "图谱服务暂时无法读取，请稍后重试。",
                },
            }
        known_documents = {"document:" + str(row[0].id) for row in all_rows}
        for node in nodes:
            if node["kind"] == "document":
                node["source_available"] = node["id"] in known_documents
                node["detail"] = (
                    "已处理的制度文档；选择全部范围可查看跨文档关联。"
                    if node["source_available"]
                    else "原文引用的制度，尚未关联到唯一的已处理文档。"
                )
        by_node = {node["id"]: node for node in nodes}
        for node in nodes:
            node["sources"] = []
        for edge in edges:
            eid = edge.pop("evidence_id")
            if eid not in evidence:
                raise GraphProblem(
                    "graph_evidence_missing", "图谱来源不完整，请重新生成图谱", status_code=503
                )
            edge["sources"] = [eid]
            for endpoint in ["source", "target"]:
                if eid not in by_node[edge[endpoint]]["sources"]:
                    by_node[edge[endpoint]]["sources"].append(eid)
        return {**result, "nodes": nodes, "edges": edges, "truncated": truncated}
