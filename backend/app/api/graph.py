import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from app.graph.service import GraphProblem, GraphService

router = APIRouter(prefix="/api/graph", tags=["graph"])
logger = logging.getLogger(__name__)


class BuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=100)


@router.post("/build", status_code=202)
def build_graph(body: BuildRequest, request: Request):
    try:
        result = GraphService(request.app.state.db_engine, request.app.state.settings).build(
            body.document_ids
        )
    except GraphProblem as problem:
        raise HTTPException(
            problem.status_code, {"code": problem.code, "message": str(problem)}
        ) from None
    except SQLAlchemyError:
        raise HTTPException(503, "暂时无法保存图谱任务，请稍后重试。") from None
    if request.app.state.settings.dispatch_on_accept:
        from app.tasks.dispatch import dispatch_pending

        try:
            dispatch_pending(
                request.app.state.settings, job_ids=[UUID(job["id"]) for job in result["jobs"]]
            )
        except Exception as error:
            logger.warning("Graph dispatch delayed (%s)", type(error).__name__)
    return result


@router.get("")
def get_graph(request: Request, document_id: UUID | None = None):
    try:
        return GraphService(request.app.state.db_engine, request.app.state.settings).read(
            document_id
        )
    except GraphProblem as problem:
        raise HTTPException(
            problem.status_code, {"code": problem.code, "message": str(problem)}
        ) from None
    except SQLAlchemyError:
        raise HTTPException(503, "暂时无法读取图谱任务，请稍后重试。") from None
