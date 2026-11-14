"""Catch stale ORM objects overwriting a stop or a newer scope after acquiring a row lock."""

from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


def test_completed_answer_cannot_overwrite_stop_from_another_transaction(test_engine):
    from app.models import ChatMessage, ChatSession
    from app.persistence import complete_answer

    session_id, user_id, assistant_id = uuid4(), uuid4(), uuid4()
    with Session(test_engine) as setup, setup.begin():
        setup.add(ChatSession(id=session_id))
        setup.flush()
        setup.add(ChatMessage(id=user_id, session_id=session_id, sequence_no=1, role="user"))
        setup.flush()
        setup.add(
            ChatMessage(
                id=assistant_id,
                session_id=session_id,
                sequence_no=2,
                role="assistant",
                reply_to_message_id=user_id,
                client_request_id=uuid4(),
                status="generating",
                request_snapshot={"schema_version": 1, "documents": []},
            )
        )
    try:
        with Session(test_engine) as stale:
            old = stale.get(ChatMessage, assistant_id)
            assert old.status == "generating"
            with Session(test_engine) as other, other.begin():
                other.get(ChatMessage, assistant_id).status = "stopped"
            with pytest.raises(ValueError):
                complete_answer(stale, assistant_id, "未找到依据。", [], answer_kind="refused")
        with Session(test_engine) as check:
            assert check.get(ChatMessage, assistant_id).status == "stopped"
    finally:
        with Session(test_engine) as cleanup, cleanup.begin():
            cleanup.execute(delete(ChatMessage).where(ChatMessage.session_id == session_id))
            cleanup.execute(delete(ChatSession).where(ChatSession.id == session_id))


def test_stale_scope_object_cannot_bypass_revision_check(test_engine):
    from app.contracts import SessionScope
    from app.models import ChatSession
    from app.persistence import save_scope

    session_id = uuid4()
    with Session(test_engine) as setup, setup.begin():
        setup.add(ChatSession(id=session_id))
    try:
        with Session(test_engine) as stale:
            old = stale.get(ChatSession, session_id)
            assert old.scope_revision == 0
            with Session(test_engine) as other, other.begin():
                other.get(ChatSession, session_id).scope_revision = 1
            with pytest.raises(ValueError):
                save_scope(stale, session_id, SessionScope(), 0)
    finally:
        with Session(test_engine) as cleanup, cleanup.begin():
            cleanup.execute(delete(ChatSession).where(ChatSession.id == session_id))
