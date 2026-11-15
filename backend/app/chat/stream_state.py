"""Short, fenced transactions for drafts and canonical streaming message states."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import null, select
from sqlalchemy.orm import Session

from app.chat.service import ChatProblem, ChatService, message_view
from app.models import ChatMessage, ChatSession
from app.persistence import complete_answer

ACTIVE = {"queued", "retrieving", "generating"}


def expire_message(message):
    if (
        message.status not in ACTIVE
        or not message.lease_expires_at
        or message.lease_expires_at > datetime.now(UTC)
    ):
        return False
    message.status, message.lease_expires_at = "failed", None
    message.error = {
        "code": "request_expired",
        "message": "上次回答连接已中断，保留的内容尚未完成，可重新生成。",
        "retryable": True,
    }
    return True


class StreamState:
    def __init__(self, engine, settings):
        self.engine, self.settings = engine, settings
        self.chat = ChatService(engine, settings)

    def result(self, identity):
        with Session(self.engine) as db:
            message = db.get(ChatMessage, identity)
            return {
                "user": message_view(db, db.get(ChatMessage, message.reply_to_message_id)),
                "assistant": message_view(db, message),
            }

    def lock_session(self, db, session_id):
        session = db.scalar(
            select(ChatSession).where(ChatSession.id == session_id).with_for_update()
        )
        if session is None or session.deleted_at is not None:
            raise ChatProblem("session_missing", "会话不存在", 404)

    def save(self, run, *, phase=None, final=None, failure=None):
        with Session(self.engine) as db, db.begin():
            self.lock_session(db, run.session_id)
            message = self.chat.live_message(db, run.identity, run.attempt)
            if run.cancelled.is_set():
                raise ChatProblem("request_stopped", "回答已停止")
            message.content = run.draft
            message.lease_expires_at = datetime.now(UTC) + timedelta(
                seconds=max(90, self.settings.model_timeout_seconds + 30)
            )
            message.updated_at = datetime.now(UTC)
            message.request_snapshot = {
                **run.snapshot,
                "transport": "sse",
                "attempt_no": run.attempt,
                "answer_mode": run.mode,
                "web_search_requested": run.web_search,
                "warnings": run.warnings,
                "details": run.details,
                "stream_phase": phase or (message.request_snapshot or {}).get("stream_phase"),
            }
            if phase:
                message.status = (
                    "generating" if phase in {"generating", "validating"} else "retrieving"
                )
            if final:
                content, citations, kind = final
                complete_answer(db, run.identity, content, citations, answer_kind=kind)
            if failure:
                message.status, message.lease_expires_at = "failed", None
                message.error = failure

    def stop(
        self, session_id, request_id, text, attempt, *, draft=None, reason="user", web_search=False
    ):
        session_id, request_id = UUID(str(session_id)), UUID(str(request_id))
        with Session(self.engine) as db:
            message = db.scalar(
                select(ChatMessage).where(
                    ChatMessage.session_id == session_id,
                    ChatMessage.client_request_id == request_id,
                )
            )
            missing = message is None
        if missing:
            try:
                self.chat.start(
                    session_id,
                    request_id,
                    text,
                    retry_attempt=attempt if attempt > 1 else None,
                    transport="sse",
                    web_search=web_search,
                )
            except ChatProblem as error:
                if error.code != "request_incomplete":
                    raise
        with Session(self.engine) as db, db.begin():
            self.lock_session(db, session_id)
            message = db.scalar(
                select(ChatMessage)
                .where(
                    ChatMessage.session_id == session_id,
                    ChatMessage.client_request_id == request_id,
                )
                .with_for_update()
            )
            if message is None:
                raise ChatProblem("request_missing", "找不到本次回答", 404)
            user = db.get(ChatMessage, message.reply_to_message_id)
            if user.content != text:
                raise ChatProblem("request_conflict", "同一请求标识不能用于不同问题")
            if (
                bool((message.request_snapshot or {}).get("web_search_requested", False))
                != web_search
            ):
                raise ChatProblem("request_conflict", "停止请求的联网选择不一致，请刷新查看")
            if (message.request_snapshot or {}).get("attempt_no", 1) != attempt:
                raise ChatProblem("request_changed", "回答尝试已更新，请刷新查看")
            if message.status in ACTIVE:
                if (message.request_snapshot or {}).get("transport") != "sse":
                    raise ChatProblem("not_streaming", "此回答未通过流式入口提交")
                if draft is not None:
                    message.content = draft
                message.status, message.answer_kind, message.error = "stopped", None, null()
                message.stop_requested_at = message.updated_at = datetime.now(UTC)
                message.lease_expires_at = None
                snapshot = dict(message.request_snapshot or {})
                details = dict(
                    snapshot.get("details")
                    or {
                        "version": 1,
                        "intent": None,
                        "stages": [],
                        "retrieval": None,
                        "total_ms": None,
                    }
                )
                details["outcome"] = "stopped" if reason == "user" else "interrupted"
                snapshot.update(details=details, stop_reason=reason)
                message.request_snapshot = snapshot
            db.flush()
            return {"user": message_view(db, user), "assistant": message_view(db, message)}
