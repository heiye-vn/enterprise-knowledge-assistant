from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.integration


@pytest.fixture
def chat(db, source):
    from app.models import ChatMessage, ChatSession

    document, version, job, chunk = source
    job.status, job.stage, job.finished_at = "ready", "done", datetime.now(UTC)
    db.flush()
    version.active_import_job_id = job.id
    document.current_version_id = version.id
    session = ChatSession(id=uuid4(), next_message_seq=3)
    db.add(session)
    db.flush()
    user = ChatMessage(
        id=uuid4(),
        session_id=session.id,
        sequence_no=1,
        role="user",
        content="电子发票的要求？",
    )
    db.add(user)
    db.flush()
    assistant = ChatMessage(
        id=uuid4(),
        session_id=session.id,
        sequence_no=2,
        role="assistant",
        status="generating",
        reply_to_message_id=user.id,
        client_request_id=uuid4(),
        request_snapshot={
            "schema_version": 1,
            "documents": [
                {
                    "document_id": str(document.id),
                    "version_id": str(version.id),
                    "job_id": str(job.id),
                    "graph_job_id": None,
                }
            ],
        },
    )
    db.add(assistant)
    db.flush()
    return session, user, assistant, chunk


def test_answer_and_citations_roundtrip_keep_original_version(db, chat, source):
    from app.models import ChatMessage, MessageCitation
    from app.persistence import complete_answer

    _, _, assistant, chunk = chat
    document, version, job, _ = source
    complete_answer(
        db,
        assistant.id,
        "应提交原始 PDF 文件。[1]",
        [
            {"chunk_id": chunk.id, "citation_no": 1, "quote": "应提交原始 PDF 文件"},
        ],
        answer_kind="answered",
    )
    db.expire_all()
    saved = db.get(ChatMessage, assistant.id)
    citations = db.scalars(
        select(MessageCitation).where(
            MessageCitation.message_id == assistant.id,
        )
    ).all()
    assert saved.status == "completed"
    assert saved.content == "应提交原始 PDF 文件。[1]"
    assert len(citations) == 1
    assert citations[0].source_snapshot["version_id"] == str(version.id)
    assert citations[0].source_snapshot["job_id"] == str(job.id)
    assert citations[0].source_snapshot["page_start"] == 1
    document.title = "重命名后的制度"
    db.flush()
    assert citations[0].source_snapshot["document_title"] == "费用报销管理制度"


@pytest.mark.parametrize("mutation", ["scope", "quote", "number", "user_role", "stopped"])
def test_invalid_citation_or_terminal_message_cannot_commit_final_answer(db, chat, mutation):
    from app.models import MessageCitation
    from app.persistence import complete_answer

    _, user, assistant, chunk = chat
    target = assistant.id
    citation = {"chunk_id": chunk.id, "citation_no": 1, "quote": "应提交原始 PDF 文件"}
    if mutation == "scope":
        assistant.request_snapshot = {"schema_version": 1, "documents": []}
    elif mutation == "quote":
        citation["quote"] = "截图可以替代原件"
    elif mutation == "number":
        citation["citation_no"] = 2
    elif mutation == "user_role":
        target = user.id
    else:
        assistant.status = "stopped"
    db.flush()
    original_status = assistant.status
    with pytest.raises(ValueError):
        complete_answer(db, target, "应提交原始 PDF 文件。[1]", [citation], answer_kind="answered")
    assert db.scalars(select(MessageCitation)).all() == []
    assert assistant.status == original_status


def test_scope_update_persists_and_rejects_stale_revision(db, chat, source):
    from app.contracts import SessionScope
    from app.persistence import save_scope

    session, *_ = chat
    document, *_ = source
    save_scope(db, session.id, SessionScope(mode="custom", document_ids=[document.id]), 0)
    db.refresh(session)
    assert session.scope == {"mode": "custom", "document_ids": [str(document.id)]}
    assert session.scope_revision == 1
    with pytest.raises(ValueError):
        save_scope(db, session.id, SessionScope(), 0)
    assert session.scope["mode"] == "custom"


def test_unavailable_document_cannot_enter_scope(db, chat):
    from app.contracts import SessionScope
    from app.persistence import save_scope

    session, *_ = chat
    with pytest.raises(ValueError):
        save_scope(db, session.id, SessionScope(mode="custom", document_ids=[uuid4()]), 0)
    assert session.scope_revision == 0


def test_only_one_active_assistant_per_session(db, chat):
    from app.models import ChatMessage

    session, *_ = chat
    second_user = ChatMessage(
        id=uuid4(),
        session_id=session.id,
        sequence_no=3,
        role="user",
        content="第二个问题",
    )
    db.add(second_user)
    db.flush()
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(
            ChatMessage(
                id=uuid4(),
                session_id=session.id,
                sequence_no=4,
                role="assistant",
                status="queued",
                reply_to_message_id=second_user.id,
                client_request_id=uuid4(),
                request_snapshot={},
            )
        )
        db.flush()


def test_reply_cannot_cross_sessions(db, chat):
    from app.models import ChatMessage, ChatSession

    original_session, *_ = chat
    user = ChatMessage(
        id=uuid4(),
        session_id=original_session.id,
        sequence_no=3,
        role="user",
        content="尚未答复的问题",
    )
    db.add(user)
    db.flush()
    other = ChatSession(id=uuid4())
    db.add(other)
    db.flush()
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(
            ChatMessage(
                id=uuid4(),
                session_id=other.id,
                sequence_no=1,
                role="assistant",
                status="queued",
                reply_to_message_id=user.id,
                client_request_id=uuid4(),
                request_snapshot={},
            )
        )
        db.flush()
