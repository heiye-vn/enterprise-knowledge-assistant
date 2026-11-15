from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.documents import get_db
from app.api.parsing import version_or_404
from app.models import Chunk, ProcessingJob
from app.retrieval.search import SearchProblem, SearchService, source_query, source_view

router = APIRouter(prefix="/api", tags=["retrieval"])


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=2, max_length=1000)
    document_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=500)
    top_k: int = Field(default=6, ge=1, le=20)
    use_graph: bool = False

    @model_validator(mode="after")
    def unique_scope(self):
        if self.document_ids and len(set(self.document_ids)) != len(self.document_ids):
            raise ValueError("检索范围不能包含重复文档")
        return self


@router.post("/search")
def search(body: SearchRequest, request: Request):
    try:
        return SearchService(request.app.state.db_engine, request.app.state.settings).retrieve(
            body.question,
            document_ids=body.document_ids,
            top_k=body.top_k,
            use_graph=body.use_graph,
        )
    except SearchProblem as problem:
        raise HTTPException(
            problem.status_code, {"code": problem.code, "message": str(problem)}
        ) from None
    except SQLAlchemyError:
        raise HTTPException(
            503,
            {"code": "search_storage_unavailable", "message": "暂时无法读取检索索引，请稍后重试"},
        ) from None


@router.get("/chunks/{chunk_id}")
def chunk_source(chunk_id: UUID, db: Annotated[Session, Depends(get_db)]):
    row = db.execute(source_query().where(Chunk.id == chunk_id)).one_or_none()
    if row is None:
        raise HTTPException(404, "切片不存在或尚未发布")
    return source_view(*row)


@router.get("/document-versions/{version_id}/chunks")
def version_chunks(
    version_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    job_id: UUID | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
):
    version = version_or_404(db, version_id, archived_job_id=job_id)
    identity = job_id or version.active_import_job_id
    if identity is None:
        return {"items": [], "total": 0, "job_id": None}
    job = db.get(ProcessingJob, identity)
    if (
        job is None
        or job.version_id != version_id
        or job.status != "ready"
        or job.job_type != "import"
    ):
        if job_id:
            raise HTTPException(404, "该任务的切片尚未发布")
        return {"items": [], "total": 0, "job_id": None}
    total = db.scalar(select(func.count()).select_from(Chunk).where(Chunk.job_id == identity))
    rows = db.execute(
        source_query()
        .where(Chunk.job_id == identity)
        .order_by(Chunk.ordinal)
        .offset(offset)
        .limit(limit)
    )
    return {"items": [source_view(*row) for row in rows], "total": total, "job_id": str(identity)}
