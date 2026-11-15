import json
from datetime import UTC, datetime
from functools import partial
from queue import Empty
from typing import Annotated
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.documents import get_db
from app.chat.service import ChatProblem, ChatService, message_view
from app.chat.stream_state import expire_message
from app.models import ChatMessage, ChatSession

router = APIRouter(prefix="/api", tags=["chat"])


class SessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    session_id: UUID
    client_request_id: UUID
    text: str = Field(min_length=1, max_length=2000)
    retry_attempt: int | None = Field(default=None, ge=2, le=3)
    web_search: bool = False


class StopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    session_id: UUID
    client_request_id: UUID
    text: str = Field(min_length=1, max_length=2000)
    attempt_no: int = Field(default=1, ge=1, le=3)
    web_search: bool = False


def session_view(session):
    return {
        "id": str(session.id),
        "title": session.title,
        "updated_at": session.updated_at.isoformat(),
    }


@router.post("/sessions", status_code=201)
def create_session(body: SessionRequest, db: Annotated[Session, Depends(get_db)]):
    with db.begin():
        session = db.get(ChatSession, body.id)
        if session is None:
            session = ChatSession(id=body.id)
            db.add(session)
            db.flush()
        if session.deleted_at:
            raise HTTPException(404, "会话不存在")
        return session_view(session)


@router.get("/sessions")
def list_sessions(db: Annotated[Session, Depends(get_db)]):
    sessions = db.scalars(
        select(ChatSession)
        .where(
            ChatSession.deleted_at.is_(None),
            select(ChatMessage.id).where(ChatMessage.session_id == ChatSession.id).exists(),
        )
        .order_by(ChatSession.updated_at.desc())
        .limit(100)
    )
    return {"items": [session_view(s) for s in sessions]}


@router.get("/sessions/{session_id}")
def get_session(session_id: UUID, db: Annotated[Session, Depends(get_db)]):
    with db.begin():
        session = db.scalar(
            select(ChatSession).where(ChatSession.id == session_id).with_for_update()
        )
        if session is None or session.deleted_at:
            raise HTTPException(404, "会话不存在")
        messages = list(
            db.scalars(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.sequence_no)
                .with_for_update()
            )
        )
        for message in messages:
            expire_message(message)
        db.flush()
        return {**session_view(session), "messages": [message_view(db, m) for m in messages]}


def sse_event(kind, payload):
    return "event: " + kind + "\ndata: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


@router.post("/chat/stream")
def stream_chat(body: ChatRequest, request: Request):
    manager = request.app.state.chat_streams
    try:
        run, initial = manager.start(
            body.session_id,
            body.client_request_id,
            body.text,
            retry_attempt=body.retry_attempt,
            web_search=body.web_search,
        )
    except ChatProblem as problem:
        raise HTTPException(
            problem.status_code, {"code": problem.code, "message": str(problem)}
        ) from None
    except SQLAlchemyError:
        raise HTTPException(
            503, {"code": "chat_storage_unavailable", "message": "暂时无法保存会话，请稍后重试"}
        ) from None

    async def events():
        terminal_sent = False
        try:
            yield sse_event("start", initial)
            if run is None:
                terminal_sent = True
                yield sse_event("done", initial)
                return
            while True:
                try:
                    kind, payload = await anyio.to_thread.run_sync(
                        partial(run.events.get, timeout=1)
                    )
                except Empty:
                    if run.finished.is_set():
                        kind, payload = "done", manager.state.result(run.identity)
                    else:
                        yield ": heartbeat\n\n"
                        continue
                terminal_sent = kind in {"done", "error"}
                yield sse_event(kind, payload)
                if terminal_sent:
                    break
        finally:
            if run is not None and not terminal_sent:
                with anyio.CancelScope(shield=True):
                    try:
                        await anyio.to_thread.run_sync(
                            partial(
                                manager.stop,
                                body.session_id,
                                body.client_request_id,
                                body.text,
                                run.attempt,
                                reason="disconnected",
                                web_search=run.web_search,
                            )
                        )
                    except (ChatProblem, SQLAlchemyError):
                        run.cancel()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.post("/chat/stop")
def stop_chat(body: StopRequest, request: Request):
    try:
        return request.app.state.chat_streams.stop(
            body.session_id,
            body.client_request_id,
            body.text,
            body.attempt_no,
            web_search=body.web_search,
        )
    except ChatProblem as problem:
        raise HTTPException(
            problem.status_code, {"code": problem.code, "message": str(problem)}
        ) from None
    except SQLAlchemyError:
        raise HTTPException(
            503, {"code": "chat_storage_unavailable", "message": "暂时无法确认停止状态，请稍后重试"}
        ) from None


@router.post("/chat")
def chat(body: ChatRequest, request: Request):
    if body.web_search:
        raise HTTPException(422, "联网查询请使用流式问答入口")
    try:
        return ChatService(request.app.state.db_engine, request.app.state.settings).reply(
            body.session_id, body.client_request_id, body.text, retry_attempt=body.retry_attempt
        )
    except ChatProblem as problem:
        raise HTTPException(
            problem.status_code, {"code": problem.code, "message": str(problem)}
        ) from None
    except SQLAlchemyError:
        raise HTTPException(
            503, {"code": "chat_storage_unavailable", "message": "暂时无法保存会话，请稍后重试"}
        ) from None


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: UUID, db: Annotated[Session, Depends(get_db)]):
    with db.begin():
        session = db.scalar(
            select(ChatSession).where(ChatSession.id == session_id).with_for_update()
        )
        if session is None:
            raise HTTPException(404, "会话不存在")
        if session.deleted_at is not None:
            return
        now = datetime.now(UTC)
        active = db.scalar(
            select(ChatMessage.id)
            .where(
                ChatMessage.session_id == session_id,
                ChatMessage.role == "assistant",
                ChatMessage.status.in_(["queued", "retrieving", "generating"]),
                ChatMessage.lease_expires_at > now,
            )
            .limit(1)
        )
        if active:
            raise HTTPException(409, "回答正在生成，请完成后再删除此会话")
        session.deleted_at = session.updated_at = now
