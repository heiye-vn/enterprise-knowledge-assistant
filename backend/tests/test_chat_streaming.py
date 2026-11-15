import json
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session
from test_chat_api import chat_environment as chat_environment
from test_chat_api import grounded as grounded
from test_import_api import import_environment as import_environment
from test_indexing_jobs import indexed_environment as indexed_environment

from app.chat.service import ChatService
from app.model_clients import ModelClient
from app.models import ChatMessage

pytestmark = pytest.mark.integration


def terminal(run):
    for _ in range(100):
        kind, payload = run.events.get(timeout=5)
        if kind == "done":
            return payload
    pytest.fail("stream did not reach a terminal event")


def first_delta(run):
    for _ in range(30):
        kind, payload = run.events.get(timeout=5)
        if kind == "delta":
            return payload["text"]
        assert kind != "done", payload
    pytest.fail("no actual model delta")


def test_general_stream_persists_real_increment_before_completion(chat_environment, monkeypatch):
    client, _, new_session = chat_environment
    release = Event()
    monkeypatch.setattr("app.chat.streaming.plan_reply", lambda *_a, **_k: {"mode": "general"})

    def stream(*_a, **_k):
        yield "第一段"
        assert release.wait(5)
        yield "，第二段。"

    monkeypatch.setattr(ModelClient, "stream", stream)
    identity = new_session()
    manager = client.app.state.chat_streams
    run, initial = manager.start(identity, str(uuid4()), "介绍检索")
    try:
        assert first_delta(run) == "第一段"
        current = client.get("/api/sessions/" + identity).json()["messages"][-1]
        assert current["status"] == "generating" and current["content"] == "第一段"
        assert not current["citations"] and not current["answer_kind"]
    finally:
        release.set()
    result = terminal(run)
    assert result["assistant"]["content"] == "第一段，第二段。"
    assert result["assistant"]["status"] == "completed"
    replay, saved = manager.start(identity, initial["assistant"]["client_request_id"], "介绍检索")
    assert replay is None and saved == result


def test_grounded_stream_withholds_citations_until_final_validation(grounded, monkeypatch):
    client, new_session, _, _ = grounded
    release = Event()
    monkeypatch.setattr(
        "app.chat.streaming.plan_reply",
        lambda *_a, **_k: {"mode": "knowledge", "query": "6000元报销审批"},
    )

    def stream(*_a, **_k):
        yield '{"answerable":true,"answer":"需要直属主管'
        assert release.wait(5)
        yield '、部门负责人和财务经理审批。[1]","citations":[{"source":1}]}'

    monkeypatch.setattr(ModelClient, "stream", stream)
    identity = new_session()
    run, _ = client.app.state.chat_streams.start(identity, str(uuid4()), "6000元谁审批？")
    try:
        assert first_delta(run) == "需要直属主管"
        current = client.get("/api/sessions/" + identity).json()["messages"][-1]
        assert not current["citations"] and current["status"] == "generating"
    finally:
        release.set()
    result = terminal(run)["assistant"]
    assert result["status"] == "completed" and len(result["citations"]) == 1
    assert result["content"].endswith("审批。[1]")


def test_stop_preserves_draft_and_late_attempt_cannot_overwrite_regeneration(
    chat_environment, monkeypatch
):
    client, _, new_session = chat_environment
    release = Event()
    calls = []
    monkeypatch.setattr("app.chat.streaming.plan_reply", lambda *_a, **_k: {"mode": "general"})

    def stream(*_a, **_k):
        calls.append(True)
        if len(calls) == 1:
            yield "未完成草稿"
            assert release.wait(5)
            yield "迟到的旧内容"
        else:
            yield "重新生成的完整回答"

    monkeypatch.setattr(ModelClient, "stream", stream)
    identity, request = new_session(), str(uuid4())
    manager = client.app.state.chat_streams
    first, _ = manager.start(identity, request, "解释一个概念")
    try:
        assert first_delta(first) == "未完成草稿"
        stopped = manager.stop(identity, request, "解释一个概念", 1)
        assert stopped["assistant"]["status"] == "stopped"
        assert (
            stopped["assistant"]["content"] == "未完成草稿"
            and not stopped["assistant"]["citations"]
        )
        second, _ = manager.start(identity, request, "解释一个概念", retry_attempt=2)
        assert terminal(second)["assistant"]["content"] == "重新生成的完整回答"
    finally:
        release.set()
    assert first.finished.wait(5)
    messages = client.get("/api/sessions/" + identity).json()["messages"]
    assert len(messages) == 2 and messages[-1]["content"] == "重新生成的完整回答"
    assert messages[-1]["attempt_no"] == 2


def test_invalid_citations_never_turn_streamed_draft_into_verified_answer(grounded, monkeypatch):
    client, new_session, _, _ = grounded
    monkeypatch.setattr(
        "app.chat.streaming.plan_reply",
        lambda *_a, **_k: {"mode": "knowledge", "query": "报销审批"},
    )
    monkeypatch.setattr(
        ModelClient,
        "stream",
        lambda *_a, **_k: iter(
            [
                json.dumps(
                    {
                        "answerable": True,
                        "answer": "尚未校验的文本[99]",
                        "citations": [{"source": 99}],
                    },
                    ensure_ascii=False,
                )
            ]
        ),
    )
    run, _ = client.app.state.chat_streams.start(new_session(), str(uuid4()), "6000元审批？")
    result = terminal(run)["assistant"]
    assert result["status"] == "failed" and not result["citations"] and not result["answer_kind"]
    assert result["content"] == "尚未校验的文本[99]"


def test_stop_before_stream_start_is_idempotent_and_does_not_call_model(
    chat_environment, monkeypatch
):
    client, _, new_session = chat_environment
    monkeypatch.setattr(
        ModelClient,
        "stream",
        lambda *_a, **_k: pytest.fail("cancelled request must not call model"),
    )
    identity, request = new_session(), str(uuid4())
    body = {
        "session_id": identity,
        "client_request_id": request,
        "text": "取消这次回答",
        "attempt_no": 1,
    }
    response = client.post("/api/chat/stop", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["assistant"]["status"] == "stopped"
    replay = client.post(
        "/api/chat/stream", json={key: value for key, value in body.items() if key != "attempt_no"}
    )
    assert replay.status_code == 200 and "event: done" in replay.text
    assert len(client.get("/api/sessions/" + identity).json()["messages"]) == 2


def test_refresh_recovers_expired_stream_without_losing_saved_draft(chat_environment, test_engine):
    client, settings, new_session = chat_environment
    identity = new_session()
    _, message_id, _, _ = ChatService(test_engine, settings).start(
        UUID(identity), uuid4(), "中断回答", transport="sse"
    )
    with Session(test_engine) as db, db.begin():
        message = db.get(ChatMessage, message_id)
        message.content = "服务器已保存的草稿"
        message.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    result = client.get("/api/sessions/" + identity).json()["messages"][-1]
    assert result["status"] == "failed" and result["content"] == "服务器已保存的草稿"
    assert result["error"]["retryable"] and not result["citations"]


def test_web_switch_runs_one_search_and_publishes_only_validated_web_sources(
    chat_environment, monkeypatch
):
    from app.tools.web_search import TavilySearch

    client, _, new_session = chat_environment
    calls = []
    monkeypatch.setattr(
        "app.chat.streaming.plan_reply",
        lambda *_a, **_k: {"mode": "general", "query": "Python release"},
    )

    def search(self, query):
        calls.append(query)
        return {
            "provider": "tavily",
            "query": query,
            "queried_at": "2026-11-15T00:00:00+00:00",
            "results": [
                {
                    "number": 1,
                    "url": "https://www.python.org/a",
                    "title": "Python",
                    "content": "Release date",
                }
            ],
        }

    monkeypatch.setattr(TavilySearch, "search", search)
    monkeypatch.setattr(
        ModelClient,
        "stream",
        lambda *_a, **_k: iter(
            ['{"answerable":true,"answer":"Released.[1]","citations":[{"source":1}]}']
        ),
    )
    identity, request = new_session(), str(uuid4())
    manager = client.app.state.chat_streams
    run, _ = manager.start(identity, request, "Python 新版本", web_search=True)
    answer = terminal(run)["assistant"]
    assert answer["answer_mode"] == "web" and answer["citations"] == []
    assert answer["web_sources"][0]["url"] == "https://www.python.org/a"
    assert answer["web_search_requested"] and answer["details"]["web"]["status"] == "completed"
    replay, saved = manager.start(identity, request, "Python 新版本", web_search=True)
    assert replay is None and saved["assistant"] == answer and calls == ["Python release"]
    from app.chat.service import ChatProblem

    with pytest.raises(ChatProblem):
        manager.start(identity, request, "Python 新版本", web_search=False)


def test_web_opt_in_cannot_bypass_enterprise_document_evidence(grounded, monkeypatch):
    from app.tools.web_search import TavilySearch

    client, new_session, _, _ = grounded
    monkeypatch.setattr(
        "app.chat.streaming.plan_reply",
        lambda *_a, **_k: {"mode": "knowledge", "query": "6000元审批"},
    )
    monkeypatch.setattr(
        TavilySearch, "search", lambda *_a, **_k: pytest.fail("company facts cannot search the web")
    )
    monkeypatch.setattr(
        ModelClient,
        "stream",
        lambda *_a, **_k: iter(
            [
                '{"answerable":true,"answer":"主管、部门负责人、财务经理审批。[1]","citations":[{"source":1}]}'
            ]
        ),
    )
    run, _ = client.app.state.chat_streams.start(
        new_session(), str(uuid4()), "我司6000元谁审批？", web_search=True
    )
    answer = terminal(run)["assistant"]
    assert answer["answer_mode"] == "knowledge" and len(answer["citations"]) == 1
    assert not answer["web_sources"] and answer["details"]["web"]["status"] == "skipped"


def test_web_failure_preserves_failed_tool_stage_and_no_fake_sources(chat_environment, monkeypatch):
    from app.tools.web_search import TavilySearch, WebSearchProblem

    client, _, new_session = chat_environment
    monkeypatch.setattr(
        "app.chat.streaming.plan_reply",
        lambda *_a, **_k: {"mode": "general", "query": "public question"},
    )

    def fail(*_a):
        raise WebSearchProblem("web_search_timeout", "联网搜索超时", retryable=True)

    monkeypatch.setattr(TavilySearch, "search", fail)
    monkeypatch.setattr(
        ModelClient,
        "stream",
        lambda *_a, **_k: pytest.fail("search failure must not pretend to answer"),
    )
    run, _ = client.app.state.chat_streams.start(
        new_session(), str(uuid4()), "公开最新消息", web_search=True
    )
    answer = terminal(run)["assistant"]
    assert answer["status"] == "failed" and not answer["web_sources"]
    assert (
        answer["details"]["web"]["status"] == "failed"
        and answer["details"]["stages"][-1]["key"] == "web_search"
    )


def test_web_stop_before_start_and_retry_keep_original_option(chat_environment, monkeypatch):
    from app.tools.web_search import TavilySearch

    client, _, new_session = chat_environment
    identity, request = new_session(), str(uuid4())
    stop = {
        "session_id": identity,
        "client_request_id": request,
        "text": "Python 新版本",
        "attempt_no": 1,
        "web_search": True,
    }
    response = client.post("/api/chat/stop", json=stop)
    assert response.status_code == 200 and response.json()["assistant"]["web_search_requested"]
    replay = client.post(
        "/api/chat/stream", json={k: v for k, v in stop.items() if k != "attempt_no"}
    )
    assert replay.status_code == 200 and '"status": "stopped"' in replay.text
    monkeypatch.setattr(
        "app.chat.streaming.plan_reply",
        lambda *_a, **_k: {"mode": "general", "query": "Python release"},
    )
    monkeypatch.setattr(
        TavilySearch,
        "search",
        lambda *_a: {"provider": "tavily", "query": "Python release", "results": []},
    )
    run, _ = client.app.state.chat_streams.start(
        identity, request, "Python 新版本", retry_attempt=2, web_search=True
    )
    result = terminal(run)["assistant"]
    assert (
        result["status"] == "completed"
        and result["answer_kind"] == "refused"
        and not result["web_sources"]
    )
    assert result["details"]["outcome"] == "web_no_results"
    assert len(client.get("/api/sessions/" + identity).json()["messages"]) == 2
