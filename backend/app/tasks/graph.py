"""One bounded extraction batch per lease; publish only a fenced immutable projection."""

import json
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from neo4j.exceptions import DriverError, Neo4jError
from sqlalchemy import null, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import create_db_engine
from app.graph.extraction import (
    SYSTEM,
    Candidate,
    build_units,
    validate_candidate,
    validate_response,
)
from app.graph.service import GraphProblem, graph_profile
from app.graph.store import GraphStore
from app.model_clients import ModelClient, ModelProblem
from app.models import Chunk, Document, DocumentContent, DocumentVersion, ProcessingJob
from app.retrieval.search import source_query, source_view

logger = logging.getLogger(__name__)


class LostGraphLease(Exception):
    pass


def live_job(db, identity, token):
    job = db.scalar(
        select(ProcessingJob)
        .where(ProcessingJob.id == identity)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        job is None
        or job.status != "running"
        or job.lease_token != token
        or (job.lease_expires_at is None or job.lease_expires_at <= datetime.now(UTC))
    ):
        raise LostGraphLease()
    return job


def current_source(db, job):
    row = db.execute(
        select(Document, DocumentVersion)
        .join(DocumentVersion, Document.current_version_id == DocumentVersion.id)
        .where(
            DocumentVersion.id == job.version_id,
            Document.deleted_at.is_(None),
            DocumentVersion.active_import_job_id == job.source_job_id,
        )
    ).one_or_none()
    if row is None:
        raise GraphProblem("graph_source_changed", "文档内容已更新或移除，请重新生成图谱")
    source = db.get(ProcessingJob, job.source_job_id)
    if source is None or source.status != "ready":
        raise GraphProblem("graph_source_unavailable", "原文索引尚未就绪")
    return row


def claim(engine, settings, identity):
    with Session(engine) as db, db.begin():
        job = db.scalar(
            select(ProcessingJob)
            .where(ProcessingJob.id == identity, ProcessingJob.job_type == "graph")
            .with_for_update()
        )
        if job is None or job.status != "queued":
            return None
        cp = dict(job.checkpoint)
        continuation = cp.pop("continue", False)
        if not continuation and job.attempt_no >= job.max_attempts:
            return None
        if not continuation:
            job.attempt_no += 1
        job.checkpoint = cp
        job.status = "running"
        graph = cp.get("graph", {})
        job.stage = (
            "projecting"
            if graph.get("validated")
            else ("validating" if graph.get("extraction_complete") else "extracting")
        )
        job.error, job.finished_at = null(), None
        job.lease_token += 1
        job.lease_owner = str(uuid4())
        job.lease_expires_at = datetime.now(UTC) + timedelta(
            seconds=max(settings.job_lease_seconds, settings.model_timeout_seconds + 30)
        )
        job.started_at = job.started_at or datetime.now(UTC)
        return job.lease_token


def continue_job(engine, identity, token, graph, stage):
    with Session(engine) as db, db.begin():
        job = live_job(db, identity, token)
        current_source(db, job)
        job.checkpoint = {"graph": graph, "continue": True}
        job.status, job.stage = "queued", stage
        job.lease_owner = job.lease_expires_at = None
        job.next_dispatch_at = datetime.now(UTC)


def extract_batch(settings, batch):
    messages = [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": json.dumps(
                {"units": [unit.payload() for unit in batch]}, ensure_ascii=False
            ),
        },
    ]
    for attempt in range(2):
        try:
            with ModelClient(settings) as model:
                return model.complete(messages, max_tokens=6500, purpose="graph_extract")
        except ModelProblem as error:
            if attempt or error.transport_code not in {
                "connect_error",
                "connect_timeout",
                "dns_error",
            }:
                raise
            logger.warning(
                "Graph connection setup failed; retrying connection once (%s)", error.transport_code
            )


def process_graph(job_id, settings=None):
    settings = settings or Settings()
    identity = UUID(job_id)
    engine = create_db_engine(settings)
    token = None
    try:
        token = claim(engine, settings, identity)
        if token is None:
            return
        with Session(engine) as db:
            job = db.get(ProcessingJob, identity)
            current_source(db, job)
            config, graph = job.config, dict(job.checkpoint.get("graph", {}))
            if (
                config["profile"] != graph_profile(settings)
                or config["namespace"] != settings.graph_namespace
            ):
                raise GraphProblem("graph_config_changed", "模型或图谱配置已变化，请重新生成图谱")
            parsed = db.get(DocumentContent, job.source_job_id)
            if parsed is None:
                raise GraphProblem("graph_source_missing", "原文正文不可用，请先完成文档处理")
            sources = [
                source_view(*row)
                for row in db.execute(
                    source_query().where(Chunk.job_id == job.source_job_id).order_by(Chunk.ordinal)
                )
            ]
            units = build_units(parsed.blocks, sources)
        eligible = [unit for unit in units if len(unit.text) + len(unit.context) < 24000]
        maximum = config["profile"]["max_units"]
        eligible = eligible[:maximum]
        graph.update(
            unit_count=len(eligible),
            unit_total=len(units),
            unit_limit_reached=len(eligible) < len(units),
        )
        graph.setdefault("cursor", 0)
        graph.setdefault("rules", [])
        graph.setdefault("rejected", [])
        if not graph.get("prepared"):
            graph["prepared"] = True
            with Session(engine) as db, db.begin():
                live = live_job(db, identity, token)
                current_source(db, live)
                live.checkpoint = {"graph": graph}
        if not graph.get("extraction_complete"):
            cursor = graph["cursor"]
            batch, budget = [], 28000
            for unit in eligible[cursor : cursor + config["profile"]["batch_size"]]:
                cost = len(unit.text) + len(unit.context)
                if batch and cost > budget:
                    break
                batch.append(unit)
                budget -= cost
            if batch:
                response = extract_batch(settings, batch)
                try:
                    accepted, rejected = validate_response(response.content, batch)
                except ValueError:
                    raise GraphProblem(
                        "graph_invalid_response",
                        "抽取结果格式未通过校验，可重试本批条款。",
                        retryable=True,
                    ) from None
                graph["rules"] = [*graph["rules"], *accepted]
                graph["rejected"] = [*graph["rejected"], *rejected]
                graph["cursor"] += len(batch)
            graph["extraction_complete"] = graph["cursor"] >= len(eligible)
            continue_job(
                engine,
                identity,
                token,
                graph,
                "validating" if graph["extraction_complete"] else "extracting",
            )
            return
        if not graph.get("validated"):
            if not graph["rules"] and graph["rejected"]:
                raise GraphProblem(
                    "graph_all_rejected",
                    "本次抽取结果全部未通过原文校验，可重试生成。",
                    retryable=True,
                )
            mapped = {unit.id: unit for unit in eligible}
            checked = []
            for rule in graph["rules"]:
                unit = mapped.get(rule["unit_id"])
                if unit is None or rule["quote"] != unit.text:
                    raise GraphProblem("graph_evidence_changed", "图谱原文校验失败，请重新生成")
                candidate = Candidate.model_validate(
                    {
                        "unit_id": rule["unit_id"],
                        "title": rule["title"],
                        "conditions": [
                            value for value in rule["conditions"] if value != unit.scope
                        ],
                        "relations": [
                            {"type": relation["type"], "target": relation["target"]}
                            for relation in rule["relations"]
                        ],
                    }
                )
                checked.append(validate_candidate(candidate, unit))
            graph["rules"], graph["validated"] = checked, True
            continue_job(engine, identity, token, graph, "projecting")
            return
        projection_id = str(identity) + ":" + str(token)
        counts = GraphStore(settings).project(projection_id, graph["rules"], config["catalog"])
        with Session(engine) as db, db.begin():
            job = live_job(db, identity, token)
            current_source(db, job)
            graph.update(projection_id=projection_id, projection_counts=counts)
            job.checkpoint = {"graph": graph}
            job.status, job.stage = "ready", "done"
            job.finished_at = datetime.now(UTC)
            job.lease_owner = job.lease_expires_at = None
            job.error = null()
    except LostGraphLease:
        logger.info("Graph worker lease superseded")
    except (GraphProblem, ModelProblem, DriverError, Neo4jError, ValueError) as error:
        if token is None:
            raise
        if isinstance(error, (DriverError, Neo4jError)):
            code, message, retryable = (
                "graph_projection_unavailable",
                "图谱服务暂不可用，抽取结果已保存，可重试。",
                True,
            )
        elif isinstance(error, ModelProblem):
            code, message, retryable = error.code, str(error), True
        elif isinstance(error, GraphProblem):
            code, message, retryable = error.code, str(error), error.retryable
        else:
            code, message, retryable = (
                "graph_validation_failed",
                "图谱内容未通过原文校验，请重新生成。",
                False,
            )
        with Session(engine) as db, db.begin():
            try:
                job = live_job(db, identity, token)
            except LostGraphLease:
                return
            job.status, job.finished_at = "failed", datetime.now(UTC)
            job.error = {
                "code": code,
                "message": message,
                "retryable": retryable,
                "stage": job.stage,
            }
            job.lease_owner = job.lease_expires_at = None
    finally:
        engine.dispose()
