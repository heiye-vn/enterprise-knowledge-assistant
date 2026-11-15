import json

import pytest

from app.chat.service import plan_reply
from app.config import Settings
from app.model_clients import ChatReply, ModelClient, ModelProblem


def route(monkeypatch, plan, question, history=None):
    def complete(self, messages, **kwargs):
        assert kwargs["purpose"] == "intent"
        return ChatReply(json.dumps(plan, ensure_ascii=False), "qwen", "test")

    monkeypatch.setattr(ModelClient, "complete", complete)
    return plan_reply(Settings(), question, history or [])


def test_clarification_is_a_valid_route_without_a_factual_answer(monkeypatch):
    plan = route(
        monkeypatch,
        {"mode": "clarify", "answer": "请问是什么假期，计划请几天？"},
        "我想请假，谁来审批？",
    )
    assert plan["mode"] == "clarify" and "几天" in plan["answer"]


def test_company_guard_does_not_discard_a_needed_clarification(monkeypatch):
    plan = route(
        monkeypatch,
        {"mode": "clarify", "answer": "请问是差旅、培训还是业务招待费用？"},
        "我们公司这笔费用能报多少？",
    )
    assert plan["mode"] == "clarify"


def test_company_guard_preserves_the_models_completed_query(monkeypatch):
    plan = route(
        monkeypatch,
        {"mode": "knowledge", "query": "公司差旅住宿费用标准 上海 600元"},
        "我们公司这个金额能报吗？",
    )
    assert plan["query"] == "公司差旅住宿费用标准 上海 600元"


def test_general_company_facts_are_forced_to_document_evidence(monkeypatch):
    plan = route(
        monkeypatch, {"mode": "general", "answer": "本公司补贴1000元"}, "本公司住房补贴是多少？"
    )
    assert plan["mode"] == "knowledge" and "answer" not in plan


@pytest.mark.parametrize(
    "plan",
    [
        {"mode": "clarify", "answer": ""},
        {"mode": "clarify", "answer": 12},
        {"mode": "knowledge", "query": ""},
        {"mode": "tool", "answer": "联网查到了"},
    ],
)
def test_invalid_routes_do_not_turn_into_answers(monkeypatch, plan):
    with pytest.raises(ModelProblem):
        route(monkeypatch, plan, "请帮我回答")


def test_topic_switch_does_not_reuse_the_previous_company_query(monkeypatch):
    plan = route(
        monkeypatch,
        {"mode": "general", "answer": "中国陆地面积约960万平方千米。"},
        "换个话题，中国国土面积多大？",
        [{"role": "user", "content": "我们公司事假四天如何审批？"}],
    )
    assert plan["mode"] == "general" and "query" not in plan


def test_stream_classification_does_not_generate_a_full_general_answer(monkeypatch):
    from app.chat.routing import plan_reply
    from app.config import Settings
    from app.model_clients import ChatReply, ModelClient

    seen = []

    def classify(self, messages, **kwargs):
        seen.append(messages[0]["content"])
        return ChatReply('{"mode":"general"}', "qwen", "test")

    monkeypatch.setattr(ModelClient, "complete", classify)
    result = plan_reply(Settings(_env_file=None), "解释一下向量检索", [], classify_only=True)
    assert result["mode"] == "general" and "answer" not in result
    assert "只判断路由，不生成通用回答" in seen[0]


def test_web_query_is_public_and_enterprise_guard_still_wins(monkeypatch):
    import json

    from app.chat.routing import plan_reply
    from app.config import Settings
    from app.model_clients import ChatReply, ModelClient

    monkeypatch.setattr(
        ModelClient,
        "complete",
        lambda *_a, **_k: ChatReply(
            json.dumps({"mode": "general", "query": "Python release"}), "qwen", "test"
        ),
    )
    settings = Settings(_env_file=None)
    assert (
        plan_reply(settings, "Python 最新发布", [], classify_only=True, web_search=True)["query"]
        == "Python release"
    )
    result = plan_reply(settings, "本公司住房补贴多少", [], classify_only=True, web_search=True)
    assert result["mode"] == "knowledge" and result["decision"] == "evidence_guard"
