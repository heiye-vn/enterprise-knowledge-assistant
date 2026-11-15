import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from test_import_api import import_environment as import_environment
from test_import_api import upload
from test_indexing_jobs import finish
from test_indexing_jobs import indexed_environment as indexed_environment

from app.model_clients import ChatReply, ModelClient, ModelProblem
from app.models import ChatMessage, ChatSession, Chunk, MessageCitation
from app.retrieval.search import SearchService, source_query, source_view

pytestmark = pytest.mark.integration


@pytest.fixture
def chat_environment(indexed_environment, test_engine):
    client, settings, _ = indexed_environment
    created = []

    def new_session():
        identity = str(uuid4())
        response = client.post("/api/sessions", json={"id": identity})
        assert response.status_code == 201, response.text
        created.append(UUID(identity))
        return identity

    yield client, settings, new_session
    with Session(test_engine) as db, db.begin():
        ids = select(ChatMessage.id).where(ChatMessage.session_id.in_(created))
        db.execute(delete(MessageCitation).where(MessageCitation.message_id.in_(ids)))
        db.execute(
            delete(ChatMessage).where(
                ChatMessage.session_id.in_(created), ChatMessage.role == "assistant"
            )
        )
        db.execute(delete(ChatMessage).where(ChatMessage.session_id.in_(created)))
        db.execute(delete(ChatSession).where(ChatSession.id.in_(created)))


def send(client, session_id, text, request_id=None):
    return client.post(
        "/api/chat",
        json={
            "session_id": session_id,
            "client_request_id": request_id or str(uuid4()),
            "text": text,
        },
    )


def test_empty_library_can_chat_normally_without_inventing_company_policy(
    chat_environment, monkeypatch
):
    client, _, new_session = chat_environment

    def route(self, messages, **kwargs):
        question = json.loads(messages[-1]["content"])["question"]
        plan = (
            {"mode": "general", "answer": "你好，我来自已配置模型。"}
            if question == "你好"
            else {"mode": "knowledge", "query": question}
        )
        return ChatReply(json.dumps(plan, ensure_ascii=False), "qwen", "test")

    monkeypatch.setattr(ModelClient, "complete", route)
    identity = new_session()
    assert client.post("/api/sessions", json={"id": identity}).status_code == 201
    greeting = send(client, identity, "你好")
    assert greeting.status_code == 200, greeting.text
    assert "你好" in greeting.json()["assistant"]["content"]
    assert greeting.json()["assistant"]["citations"] == []
    refusal = send(client, identity, "报销多少钱要总经理审批？")
    assert refusal.status_code == 200, refusal.text
    assert "未找到相关依据" in refusal.json()["assistant"]["content"]
    assert refusal.json()["assistant"]["answer_kind"] == "refused"
    history = client.get("/api/sessions/" + identity).json()
    assert len(history["messages"]) == 4
    assert identity in {s["id"] for s in client.get("/api/sessions").json()["items"]}


@pytest.fixture
def grounded(chat_environment, test_engine, monkeypatch):
    client, settings, new_session = chat_environment
    accepted = upload(
        client,
        "# 报销\n\n超过5000元且不超过20000元，由直属主管、部门负责人和财务经理审批。".encode(),
    ).json()
    assert finish(client, settings, accepted["job_id"])["status"] == "ready"
    with Session(test_engine) as db:
        row = db.execute(source_query().where(Chunk.job_id == UUID(accepted["job_id"]))).one()
        source = source_view(*row)
    seen = []
    from app.chat.service import retrieval_question

    monkeypatch.setattr(
        "app.chat.service.plan_reply",
        lambda settings, text, history: {
            "mode": "knowledge",
            "query": retrieval_question(text, history),
        },
    )

    def retrieve(self, question, **kwargs):
        seen.append(question)
        return {
            "items": [{**source, "scores": {"rerank": 0.98}}],
            "snapshot": {
                "documents": [
                    {
                        "document_id": source["document_id"],
                        "version_id": source["version_id"],
                        "job_id": source["job_id"],
                    }
                ]
            },
            "warnings": [],
            "degraded": False,
        }

    monkeypatch.setattr(SearchService, "retrieve", retrieve)
    return client, new_session, source, seen


def test_real_source_citations_persist_and_request_retry_is_idempotent(grounded, monkeypatch):
    client, new_session, source, _ = grounded
    calls = []

    def complete(self, messages, **kwargs):
        calls.append(messages)
        return ChatReply(
            json.dumps(
                {
                    "answerable": True,
                    "answer": "需要直属主管、部门负责人和财务经理审批。[1]",
                    "citations": [{"source": 1, "quote": "由直属主管、部门负责人和财务经理审批。"}],
                },
                ensure_ascii=False,
            ),
            "qwen",
            "test",
        )

    monkeypatch.setattr(ModelClient, "complete", complete)
    identity, key = new_session(), str(uuid4())
    first = send(client, identity, "6000元由谁审批？", key)
    assert first.status_code == 200, first.text
    again = send(client, identity, "6000元由谁审批？", key)
    assert first.json() == again.json() and len(calls) == 1
    answer = first.json()["assistant"]
    assert answer["citations"][0]["source"]["id"] == source["id"]
    assert answer["citations"][0]["source"]["job_id"] == source["job_id"]
    assert client.get("/api/sessions/" + identity).json()["messages"][-1] == answer
    assert send(client, identity, "不同的问题", key).status_code == 409


@pytest.mark.parametrize("invalid", ["quote", "number", "no_citation"])
def test_ungrounded_generated_answer_is_never_saved_as_completed(grounded, monkeypatch, invalid):
    client, new_session, source, _ = grounded
    data = {
        "answerable": True,
        "answer": "可以免审批。[1]",
        "citations": [{"source": 1, "quote": "可以免审批"}],
    }
    if invalid == "number":
        data["citations"][0] = {"source": 99, "quote": source["content"]}
    if invalid == "no_citation":
        data["answer"] = "可以免审批。"
        data["citations"] = []
    monkeypatch.setattr(
        ModelClient, "complete", lambda *_a, **_k: ChatReply(json.dumps(data), "qwen", "test")
    )
    identity = new_session()
    response = send(client, identity, "6000元由谁审批？")
    assert response.status_code == 503, response.text
    assistant = client.get("/api/sessions/" + identity).json()["messages"][-1]
    assert (
        assistant["status"] == "failed"
        and assistant["content"] == ""
        and not assistant["citations"]
    )


def test_unrelated_evidence_refuses_and_transport_failure_is_service_error(grounded, monkeypatch):
    client, new_session, _, _ = grounded
    monkeypatch.setattr(
        ModelClient, "complete", lambda *_a, **_k: ChatReply('{"answerable":false}', "qwen", "test")
    )
    identity = new_session()
    response = send(client, identity, "公司成立在哪一年？")
    assert (
        response.status_code == 200 and "未找到相关依据" in response.json()["assistant"]["content"]
    )

    def unavailable(*_a, **_k):
        raise ModelProblem("model_unavailable", "模型暂不可用", retryable=True)

    monkeypatch.setattr(ModelClient, "complete", unavailable)
    response = send(client, identity, "6000元由谁审批？")
    assert response.status_code == 503
    assert "未找到相关依据" not in response.json()["detail"]["message"]


def test_citation_quote_is_attached_from_source_and_followup_uses_session_history(
    grounded, monkeypatch
):
    client, new_session, source, seen = grounded
    payload = {
        "answerable": True,
        "answer": "由直属主管、部门负责人和财务经理审批。[1]",
        "citations": [{"source": 1}],
    }
    monkeypatch.setattr(
        ModelClient, "complete", lambda *_a, **_k: ChatReply(json.dumps(payload), "qwen", "test")
    )
    identity = new_session()
    response = send(client, identity, "6000元由谁审批？")
    assert response.status_code == 200, response.text
    assert response.json()["assistant"]["citations"][0]["quote"] == source["content"]
    monkeypatch.setattr(
        ModelClient, "complete", lambda *_a, **_k: ChatReply('{"answerable":false}', "qwen", "test")
    )
    assert send(client, identity, "那超过20000元呢？").status_code == 200
    assert "6000元由谁审批" in seen[-1] and "超过20000元" in seen[-1]


def test_general_knowledge_uses_model_without_search_or_fake_sources(chat_environment, monkeypatch):
    client, _, new_session = chat_environment
    calls = []

    def complete(self, messages, **kwargs):
        calls.append(messages)
        return ChatReply(
            json.dumps(
                {"mode": "general", "answer": "中国陆地国土面积约为960万平方千米。"},
                ensure_ascii=False,
            ),
            "qwen",
            "test",
        )

    monkeypatch.setattr(ModelClient, "complete", complete)
    monkeypatch.setattr(
        SearchService,
        "retrieve",
        lambda *_a, **_k: pytest.fail("general question must not require company documents"),
    )
    identity = new_session()
    response = send(client, identity, "请问中国的国土面积是多少")
    assert response.status_code == 200, response.text
    answer = response.json()["assistant"]
    assert "960万" in answer["content"] and answer["answer_mode"] == "general"
    assert answer["answer_kind"] == "answered" and not answer["citations"] and len(calls) == 1


def test_blank_sessions_are_hidden_and_deletion_hides_history_and_rejects_reuse(
    chat_environment, monkeypatch
):
    client, _, new_session = chat_environment
    identity = new_session()
    assert identity not in {s["id"] for s in client.get("/api/sessions").json()["items"]}
    monkeypatch.setattr(
        ModelClient,
        "complete",
        lambda *_a, **_k: ChatReply('{"mode":"general","answer":"你好！"}', "qwen", "test"),
    )
    assert send(client, identity, "你好").status_code == 200
    assert identity in {s["id"] for s in client.get("/api/sessions").json()["items"]}
    assert client.delete("/api/sessions/" + identity).status_code == 204
    assert client.delete("/api/sessions/" + identity).status_code == 204
    assert identity not in {s["id"] for s in client.get("/api/sessions").json()["items"]}
    assert client.get("/api/sessions/" + identity).status_code == 404
    assert send(client, identity, "你好").status_code == 404


def test_first_message_creates_session_atomically(chat_environment, monkeypatch, test_engine):
    client, _, new_session = chat_environment
    identity = new_session()
    with Session(test_engine) as db, db.begin():
        db.execute(delete(ChatSession).where(ChatSession.id == UUID(identity)))
    monkeypatch.setattr(
        ModelClient,
        "complete",
        lambda *_a, **_k: ChatReply('{"mode":"general","answer":"你好！"}', "qwen", "test"),
    )
    response = send(client, identity, "你好")
    assert response.status_code == 200, response.text
    assert client.get("/api/sessions/" + identity).json()["title"] == "你好"


def test_company_specific_question_cannot_use_general_model_facts(chat_environment, monkeypatch):
    client, _, new_session = chat_environment
    monkeypatch.setattr(
        ModelClient,
        "complete",
        lambda *_a, **_k: ChatReply('{"mode":"general","answer":"公司补贴1000元"}', "qwen", "test"),
    )
    response = send(client, new_session(), "我们公司每月住房补贴是多少？")
    assert response.status_code == 200, response.text
    assert response.json()["assistant"]["answer_mode"] == "knowledge"
    assert "未找到相关依据" in response.json()["assistant"]["content"]
    assert "1000" not in response.json()["assistant"]["content"]


def test_active_answer_cannot_be_deleted_mid_generation(chat_environment, test_engine):
    from app.chat.service import ChatService

    client, settings, new_session = chat_environment
    identity = new_session()
    ChatService(test_engine, settings).start(UUID(identity), uuid4(), "正在提问")
    assert client.delete("/api/sessions/" + identity).status_code == 409
    assert client.get("/api/sessions/" + identity).status_code == 200


def test_explicit_retry_reuses_messages_and_replayed_retry_never_regenerates(
    chat_environment, monkeypatch
):
    client, _, new_session = chat_environment
    calls = []

    def complete(*_a, **_k):
        calls.append(1)
        if len(calls) == 1:
            raise ModelProblem("model_unavailable", "连接超时", retryable=True)
        return ChatReply('{"mode":"general","answer":"你好，连接已恢复。"}', "qwen", "test")

    monkeypatch.setattr(ModelClient, "complete", complete)
    identity, key = new_session(), str(uuid4())
    assert send(client, identity, "你好", key).status_code == 503
    history = client.get("/api/sessions/" + identity).json()["messages"]
    assert history[-1]["error"]["retryable"] and history[-1]["attempt_no"] == 1
    assert send(client, identity, "你好", key).status_code == 409
    payload = {"session_id": identity, "client_request_id": key, "text": "你好", "retry_attempt": 2}
    retry = client.post("/api/chat", json=payload)
    assert retry.status_code == 200, retry.text
    again = client.post("/api/chat", json=payload)
    assert again.json() == retry.json() and len(calls) == 2
    saved = client.get("/api/sessions/" + identity).json()["messages"]
    assert [m["id"] for m in saved] == [m["id"] for m in history]
    assert saved[-1]["status"] == "completed" and saved[-1]["attempt_no"] == 2


def test_retry_requires_retryable_latest_failure_and_is_bounded(chat_environment, monkeypatch):
    client, _, new_session = chat_environment

    def fail(*_a, **_k):
        raise ModelProblem("model_unavailable", "连接超时", retryable=True)

    monkeypatch.setattr(ModelClient, "complete", fail)
    identity, key = new_session(), str(uuid4())
    assert send(client, identity, "你好", key).status_code == 503
    payload = {"session_id": identity, "client_request_id": key, "text": "你好"}
    assert client.post("/api/chat", json={**payload, "retry_attempt": 3}).status_code == 409
    assert client.post("/api/chat", json={**payload, "retry_attempt": 2}).status_code == 503
    assert client.post("/api/chat", json={**payload, "retry_attempt": 2}).status_code == 409
    assert client.post("/api/chat", json={**payload, "retry_attempt": 3}).status_code == 503
    assert client.post("/api/chat", json={**payload, "retry_attempt": 4}).status_code == 422
    assert len(client.get("/api/sessions/" + identity).json()["messages"]) == 2
    assert send(client, identity, "新问题").status_code == 503
    assert client.post("/api/chat", json={**payload, "retry_attempt": 3}).status_code == 409


def test_concurrent_retry_sends_only_one_generation(chat_environment, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    client, _, new_session = chat_environment
    identity, key = new_session(), str(uuid4())

    def fail(*_a, **_k):
        raise ModelProblem("model_unavailable", "连接失败", retryable=True)

    monkeypatch.setattr(ModelClient, "complete", fail)
    assert send(client, identity, "你好", key).status_code == 503
    entered, release = Event(), Event()
    calls = []

    def wait_for_release(*_a, **_k):
        calls.append(1)
        entered.set()
        assert release.wait(10)
        return ChatReply('{"mode":"general","answer":"连接恢复"}', "qwen", "test")

    monkeypatch.setattr(ModelClient, "complete", wait_for_release)
    payload = {"session_id": identity, "client_request_id": key, "text": "你好", "retry_attempt": 2}
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(client.post, "/api/chat", json=payload)
        try:
            assert entered.wait(10)
            assert client.post("/api/chat", json=payload).status_code == 409
        finally:
            release.set()
        assert running.result(timeout=10).status_code == 200
    assert len(calls) == 1
    assert len(client.get("/api/sessions/" + identity).json()["messages"]) == 2


def test_old_attempt_cannot_overwrite_newer_attempt(chat_environment, monkeypatch, test_engine):
    client, _, new_session = chat_environment
    identity = new_session()

    def newer_attempt(*_a, **_k):
        with Session(test_engine) as db, db.begin():
            assistant = db.scalar(
                select(ChatMessage).where(
                    ChatMessage.session_id == UUID(identity), ChatMessage.role == "assistant"
                )
            )
            assistant.request_snapshot = {"documents": [], "attempt_no": 2}
        return ChatReply('{"mode":"general","answer":"过期回答"}', "qwen", "test")

    monkeypatch.setattr(ModelClient, "complete", newer_attempt)
    assert send(client, identity, "你好").status_code == 409
    assistant = client.get("/api/sessions/" + identity).json()["messages"][-1]
    assert assistant["attempt_no"] == 2 and assistant["status"] == "retrieving"
    assert assistant["content"] == ""


def test_clarification_round_persists_and_followup_can_switch_routes(chat_environment, monkeypatch):
    client, _, new_session = chat_environment
    history_seen = []

    def complete(self, messages, **kwargs):
        payload = json.loads(messages[-1]["content"])
        history_seen.append(payload["history"])
        question = payload["question"]
        if "国土面积" in question:
            value = {"mode": "general", "answer": "中国陆地国土面积约960万平方千米。"}
        elif question == "事假四天":
            value = {"mode": "knowledge", "query": "公司事假四天审批流程"}
        else:
            value = {"mode": "clarify", "answer": "请问是什么假期，计划请几天？"}
        return ChatReply(json.dumps(value, ensure_ascii=False), "qwen", "test")

    monkeypatch.setattr(ModelClient, "complete", complete)
    identity = new_session()
    first = send(client, identity, "我想请假，谁审批？")
    assert first.status_code == 200, first.text
    answer = first.json()["assistant"]
    assert answer["answer_mode"] == "clarify" and answer["citations"] == []
    assert answer["details"]["retrieval"] is None
    assert (
        next(s for s in answer["details"]["stages"] if s["key"] == "retrieval")["status"]
        == "skipped"
    )
    second = send(client, identity, "事假四天").json()["assistant"]
    assert second["answer_mode"] == "knowledge" and second["answer_kind"] == "refused"
    assert second["details"]["intent"]["query"] == "公司事假四天审批流程"
    third = send(client, identity, "换个话题，中国国土面积多少？").json()["assistant"]
    assert third["answer_mode"] == "general" and third["details"]["retrieval"] is None
    assert any("几天" in m["content"] for m in history_seen[1])
    saved = client.get("/api/sessions/" + identity).json()["messages"]
    assert saved[1]["details"] == answer["details"]


def test_execution_details_survive_refresh_and_do_not_rerun_search(grounded, monkeypatch):
    client, new_session, source, _ = grounded
    trace = {
        "query": "审批6000元",
        "stages": [],
        "counts": {"fusion": 1},
        "candidates": [
            {
                "source": source,
                "scores": {"bm25": 1.2, "vector_distance": 0.12, "rrf": 0.032, "rerank": 0.98},
                "ranks": {"bm25": 1, "vector": 1, "fusion": 1, "rerank": 1},
                "selected": True,
            }
        ],
    }

    def retrieve(self, query, **kwargs):
        return {
            "items": [source],
            "snapshot": {
                "documents": [
                    {
                        "document_id": source["document_id"],
                        "version_id": source["version_id"],
                        "job_id": source["job_id"],
                    }
                ]
            },
            "warnings": [],
            "degraded": False,
            "trace": trace,
        }

    monkeypatch.setattr(SearchService, "retrieve", retrieve)
    monkeypatch.setattr(
        ModelClient,
        "complete",
        lambda *a, **k: ChatReply(
            '{"answerable":true,"answer":"6000元需主管、部门负责人和财务经理审批。[1]","citations":[{"source":1}]}',
            "qwen",
            "test",
        ),
    )
    identity = new_session()
    answer = send(client, identity, "6000元由谁审批？").json()["assistant"]
    details = answer["details"]
    assert details["retrieval"]["candidates"][0]["citation_no"] == 1
    assert details["retrieval"]["candidates"][0]["used_in_answer"] is True
    assert details["retrieval"]["candidates"][0]["sent_to_model"] is True
    monkeypatch.setattr(
        SearchService, "retrieve", lambda *a, **k: pytest.fail("refresh must use saved details")
    )
    saved = client.get("/api/sessions/" + identity).json()["messages"][-1]
    assert saved["details"] == details


def test_generation_failure_keeps_retrieval_details_without_claiming_citations(
    grounded, monkeypatch
):
    client, new_session, source, _ = grounded

    def unavailable(*args, **kwargs):
        raise ModelProblem("model_unavailable", "模型暂不可用", retryable=True)

    monkeypatch.setattr(ModelClient, "complete", unavailable)
    identity = new_session()
    assert send(client, identity, "6000元由谁审批？").status_code == 503
    answer = client.get("/api/sessions/" + identity).json()["messages"][-1]
    assert answer["details"]["intent"]["mode"] == "knowledge"
    assert answer["details"]["outcome"] == "failed"
    assert answer["citations"] == []
    assert (
        next(s for s in answer["details"]["stages"] if s["key"] == "answer")["status"] == "failed"
    )


def test_low_relevance_results_are_not_claimed_as_used_evidence(chat_environment, monkeypatch):
    from app.model_clients import RankedItem, Ranking

    client, settings, new_session = chat_environment
    accepted = upload(client, "# 资产\n\n离职时归还电脑和门禁卡。".encode()).json()
    assert finish(client, settings, accepted["job_id"])["status"] == "ready"
    monkeypatch.setattr(
        ModelClient,
        "rerank",
        lambda self, query, documents, top_n: Ranking(
            [RankedItem(i, 0.1) for i in range(len(documents))],
            self.settings.qwen_rerank_model,
        ),
    )

    def route_only(self, messages, **kwargs):
        assert kwargs["purpose"] == "intent", "Low relevance must not trigger answer generation"
        return ChatReply('{"mode":"knowledge","query":"火星住房补贴"}', "qwen", "test")

    monkeypatch.setattr(ModelClient, "complete", route_only)
    response = send(client, new_session(), "本公司火星住房补贴是多少？")
    assert response.status_code == 200, response.text
    answer = response.json()["assistant"]
    assert answer["answer_kind"] == "refused" and answer["citations"] == []
    assert answer["details"]["outcome"] == "low_relevance"
    candidates = answer["details"]["retrieval"]["candidates"]
    assert candidates and any(c["selected"] for c in candidates)
    assert all(not c["sent_to_model"] and not c["used_in_answer"] for c in candidates)


def test_bad_model_json_can_retry_the_original_message_without_duplicate_history(
    grounded, monkeypatch
):
    client, new_session, _, _ = grounded
    responses = iter(
        [
            "invalid JSON",
            json.dumps(
                {
                    "answerable": True,
                    "answer": "需要直属主管、部门负责人和财务经理审批。[1]",
                    "citations": [{"source": 1}],
                }
            ),
        ]
    )
    monkeypatch.setattr(
        ModelClient, "complete", lambda *_a, **_k: ChatReply(next(responses), "qwen", "test")
    )
    identity = new_session()
    request = str(uuid4())
    assert send(client, identity, "6000元由谁审批？", request).status_code == 503
    saved = client.get("/api/sessions/" + identity).json()["messages"]
    assert saved[-1]["error"]["retryable"] is True
    response = client.post(
        "/api/chat",
        json={
            "session_id": identity,
            "client_request_id": request,
            "text": "6000元由谁审批？",
            "retry_attempt": 2,
        },
    )
    assert response.status_code == 200, response.text
    messages = client.get("/api/sessions/" + identity).json()["messages"]
    assert len(messages) == 2 and messages[-1]["status"] == "completed"
