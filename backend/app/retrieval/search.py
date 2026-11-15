"""Capture published sources once, then retrieve only immutable jobs in that snapshot."""

import math
from time import monotonic
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.model_clients import ModelClient, ModelProblem
from app.models import Chunk, Document, DocumentVersion, ProcessingJob
from app.retrieval.profile import digest_profile, embedding_profile, embedding_text
from app.retrieval.ranking import cached_keyword_index, reciprocal_rank_fusion
from app.retrieval.trace import phase, retrieval_trace


class SearchProblem(ValueError):
    def __init__(self, code, message, *, status_code=503, trace=None):
        super().__init__(message)
        self.code, self.status_code, self.trace = code, status_code, trace


def source_query():
    return (
        select(Chunk, DocumentVersion, Document, ProcessingJob)
        .join(DocumentVersion, Chunk.version_id == DocumentVersion.id)
        .join(Document, DocumentVersion.document_id == Document.id)
        .join(ProcessingJob, Chunk.job_id == ProcessingJob.id)
        .where(ProcessingJob.job_type == "import", ProcessingJob.status == "ready")
    )


def source_view(chunk, version, document, job):
    return {
        "id": str(chunk.id),
        "document_id": str(document.id),
        "document_title": document.title,
        "version_id": str(version.id),
        "version_no": version.version_no,
        "job_id": str(job.id),
        "generation_no": job.generation_no,
        "filename": version.original_filename,
        "format": version.format,
        "ordinal": chunk.ordinal,
        "content": chunk.content,
        "heading_path": chunk.heading_path,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "locators": chunk.locators,
        "file_url": f"/api/document-versions/{version.id}/file",
    }


class SearchService:
    def __init__(self, engine, settings):
        self.engine, self.settings = engine, settings

    def capture(self, document_ids):
        profile_hash = digest_profile(embedding_profile(self.settings))
        with Session(self.engine) as db, db.begin():
            db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            query = (
                select(Document, DocumentVersion, ProcessingJob)
                .join(DocumentVersion, Document.current_version_id == DocumentVersion.id)
                .join(ProcessingJob, DocumentVersion.active_import_job_id == ProcessingJob.id)
                .where(
                    Document.deleted_at.is_(None),
                    ProcessingJob.status == "ready",
                    ProcessingJob.job_type == "import",
                )
            )
            if document_ids is not None:
                query = query.where(Document.id.in_(document_ids))
            rows = list(db.execute(query.order_by(Document.id)))
            if document_ids is not None and {row[0].id for row in rows} != set(document_ids):
                raise SearchProblem(
                    "selected_documents_unavailable",
                    "所选文档已移除或尚未建立索引",
                    status_code=409,
                )
            if any(job.embedding_profile_hash != profile_hash for _, _, job in rows):
                raise SearchProblem(
                    "index_profile_changed", "向量模型配置已变化，请先重建文档索引", status_code=409
                )
            snapshot = {
                "profile_hash": profile_hash,
                "documents": [
                    {
                        "document_id": str(doc.id),
                        "version_id": str(version.id),
                        "job_id": str(job.id),
                        "revision": doc.revision,
                    }
                    for doc, version, job in rows
                ],
            }
            job_ids = [job.id for _, _, job in rows]
            sources = []
            if job_ids:
                records = list(
                    db.execute(
                        source_query()
                        .where(Chunk.job_id.in_(job_ids))
                        .order_by(Chunk.job_id, Chunk.ordinal)
                    )
                )
                missing = db.scalar(
                    select(Chunk.id)
                    .where(Chunk.job_id.in_(job_ids), Chunk.embedding.is_(None))
                    .limit(1)
                )
                if missing or {row[0].job_id for row in records} != set(job_ids):
                    raise SearchProblem("incomplete_index", "已发布索引缺少切片或向量，请重建索引")
                sources = [source_view(*row) for row in records]
        return snapshot, sources

    def retrieve(self, question, *, document_ids=None, top_k=6, use_graph=False):
        snapshot, sources = self.capture(document_ids)
        if not sources:
            return {
                "items": [],
                "snapshot": snapshot,
                "degraded": False,
                "warnings": [],
                "trace": retrieval_trace(
                    question,
                    {},
                    [],
                    {},
                    {},
                    {},
                    set(),
                    [
                        phase(key, status="skipped")
                        for key in ("bm25", "vector", "fusion", "rerank")
                    ],
                    {
                        "documents": len(snapshot["documents"]),
                        "bm25": 0,
                        "vector": 0,
                        "fusion": 0,
                        "rerank_input": 0,
                        "returned": 0,
                    },
                ),
            }
        by_id = {item["id"]: item for item in sources}
        cache_key = tuple(sorted(doc["job_id"] for doc in snapshot["documents"]))
        lexical_started = monotonic()
        keyword = cached_keyword_index(
            cache_key, [embedding_text(s["content"], s["heading_path"]) for s in sources]
        )
        limit = min(100, max(30, top_k * 4))
        lexical = keyword.rank(question, limit)
        lexical_scores = {sources[i]["id"]: score for i, score in lexical}
        stages = [phase("bm25", lexical_started)]
        vector_scores = {}
        warnings = []
        with ModelClient(self.settings) as models:
            vector_started = monotonic()
            try:
                batch = models.embed_texts([question], text_type="query")
                if (
                    batch.model != self.settings.embedding_model
                    or len(batch.vectors) != 1
                    or len(batch.vectors[0]) != self.settings.embedding_dimension
                ):
                    raise ModelProblem("invalid_model_response", "查询向量校验失败")
                with Session(self.engine) as db:
                    distance = Chunk.embedding.cosine_distance(batch.vectors[0])
                    ranked = db.execute(
                        select(Chunk.id, distance.label("distance"))
                        .where(
                            Chunk.job_id.in_([UUID(value) for value in cache_key]),
                            Chunk.embedding_profile_hash == snapshot["profile_hash"],
                            Chunk.embedding_dimension == self.settings.embedding_dimension,
                            Chunk.embedding.is_not(None),
                        )
                        .order_by(distance, Chunk.id)
                        .limit(limit)
                    )
                    vector_scores = {str(identity): float(score) for identity, score in ranked}
                stages.append(phase("vector", vector_started))
            except ModelProblem as problem:
                stages.append(phase("vector", vector_started, "failed"))
                warnings.append(
                    {
                        "code": "vector_" + problem.code,
                        "message": "语义检索暂不可用，当前使用关键词结果。",
                    }
                )
            fusion_started = monotonic()
            combined = reciprocal_rank_fusion([list(vector_scores), list(lexical_scores)])
            fused = combined[:limit]
            stages.append(phase("fusion", fusion_started))
            graph_result = None
            graph_ids = []
            if use_graph:
                from app.retrieval.graph_expansion import expand_graph_sources

                graph_started = monotonic()
                graph_result = expand_graph_sources(
                    self.engine,
                    self.settings,
                    question,
                    snapshot,
                    sources,
                    [identity for identity, _ in fused[:30]],
                )
                graph_ids = graph_result["candidate_ids"]
                original_ids = {identity for identity, _ in fused}
                added_ids = [identity for identity in graph_ids if identity not in original_ids]
                graph_result.update(
                    enabled=True, seed_count=min(30, len(fused)), added_count=len(added_ids)
                )
                fusion_scores = dict(combined)
                fused += [(identity, fusion_scores.get(identity)) for identity in added_ids]
                stages.append(phase("graph", graph_started, graph_result["status"]))
                if graph_result["status"] == "failed":
                    warnings.append(
                        {
                            "code": "graph_unavailable",
                            "message": "图谱证据扩展暂不可用，已使用普通检索结果。",
                        }
                    )
            counts = {
                "documents": len(snapshot["documents"]),
                "bm25": len(lexical_scores),
                "vector": len(vector_scores),
                "fusion": len(combined),
                "rerank_input": 0,
                "returned": 0,
            }
            if not fused:
                stages.append(phase("rerank", status="skipped"))
                trace = retrieval_trace(
                    question, by_id, fused, lexical_scores, vector_scores, {}, set(), stages, counts
                )
                if warnings:
                    raise SearchProblem(
                        "retrieval_unavailable", "检索服务暂不可用，请稍后重试", trace=trace
                    )
                return {
                    "items": [],
                    "snapshot": snapshot,
                    "degraded": False,
                    "warnings": [],
                    "trace": trace,
                }
            # Bound model input without truncating source evidence.
            candidates = []
            budget = 28000
            prioritized = sorted(fused, key=lambda item: item[0] not in graph_ids)
            for identity, score in prioritized:
                value = by_id[identity]
                cost = len(embedding_text(value["content"], value["heading_path"])) + len(question)
                if cost > budget:
                    continue
                candidates.append((identity, score))
                budget -= cost
            if len(candidates) < len(fused):
                warnings.append(
                    {
                        "code": "rerank_budget_limited",
                        "message": "部分切片超出本次排序预算，保留为召回候选。",
                    }
                )
            counts["rerank_input"] = len(candidates)
            rerank_started = monotonic()
            rerank_scores = {}
            ordered = fused
            try:
                if not candidates:
                    raise ModelProblem("rerank_budget", "候选内容超出重排预算")
                ranking = models.rerank(
                    question,
                    [
                        embedding_text(by_id[i]["content"], by_id[i]["heading_path"])
                        for i, _ in candidates
                    ],
                    top_n=len(candidates),
                )
                if ranking.model != self.settings.qwen_rerank_model or len(ranking.items) != len(
                    candidates
                ):
                    raise ModelProblem("invalid_model_response", "重排数量或模型校验失败")
                seen = set()
                for item in ranking.items:
                    if (
                        type(item.index) is not int
                        or not 0 <= item.index < len(candidates)
                        or item.index in seen
                        or not math.isfinite(item.score)
                        or not 0 <= item.score <= 1
                    ):
                        raise ModelProblem("invalid_model_response", "重排索引映射校验失败")
                    seen.add(item.index)
                rerank_scores = {candidates[item.index][0]: item.score for item in ranking.items}
                ordered = [(identity, dict(candidates)[identity]) for identity in rerank_scores]
                ordered += [
                    (identity, score) for identity, score in fused if identity not in rerank_scores
                ]
                stages.append(phase("rerank", rerank_started))
            except ModelProblem as problem:
                stages.append(phase("rerank", rerank_started, "failed"))
                warnings.append(
                    {
                        "code": "rerank_" + problem.code,
                        "message": "排序服务暂不可用，当前结果未经过重排。",
                    }
                )
            items = []
            for identity, score in ordered[:top_k]:
                items.append(
                    {
                        **by_id[identity],
                        "scores": {
                            "rrf": score,
                            "vector_distance": vector_scores.get(identity),
                            "bm25": lexical_scores.get(identity),
                            "rerank": rerank_scores.get(identity),
                        },
                    }
                )
        counts["returned"] = len(items)
        trace = retrieval_trace(
            question,
            by_id,
            fused,
            lexical_scores,
            vector_scores,
            rerank_scores,
            {item["id"] for item in items},
            stages,
            counts,
            fusion_order=combined,
        )
        if graph_result is not None:
            trace["graph"] = graph_result
            for candidate in trace["candidates"]:
                candidate["graph_expanded"] = candidate["source"]["id"] in graph_ids
        return {
            "items": items,
            "trace": trace,
            "snapshot": snapshot,
            "degraded": bool(warnings),
            "warnings": warnings,
        }
