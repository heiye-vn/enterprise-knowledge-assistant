"""Validated public route decisions; no hidden model reasoning is retained."""

import json
import re

from app.model_clients import ModelClient, ModelProblem

ROUTING_SYSTEM = """你是通用对话与企业知识库问答助手。根据本轮问题和历史决定如何回答。
一般常识、地理、编程、翻译、写作、闲聊等问题，用模型自身知识正常回答。
涉及本企业内部事实、制度、员工报销/请假/采购/薪酬等规则，或用户要求依据上传文档时，才交给知识库。
不要因为产品名称是企业知识助理，就把中国国土面积等通用问题当作企业制度问题。
历史只帮助理解追问；用户切换话题时按新问题判断。企业制度没有依据时不能用通用常识编造。
返回一个 JSON 对象：
通用问题：{"mode":"general","answer":"正常回答，纯文本，不虚构知识库来源"}。
企业问题：{"mode":"knowledge","query":"结合历史补全后的本轮检索问题"}，不要在此生成企业事实答案。
问题存在无法确定的指代或缺少影响具体判断的必要条件时，先澄清：
{"mode":"clarify","answer":"一到两句简短的补充问题"}。不得在澄清中补编制度事实。
例如询问一次具体请假的审批人，但没有说明假期类型与天数；询问某笔费用可报多少，但费用类型或必要金额未知。
历史已经提供的条件不得重复询问；用户只想了解制度整体、各金额档位或一般流程时直接检索，不强迫补充个人信息。
上下文紧接澄清的“事假四天”“6000元”等补充应与原问题合并，得到完整 knowledge query。
默认查询当前工作空间的企业制度，不要求用户补充公司名称或先确认是否存在制度。
报销出行条件、费用金额、请假类别和天数已足以查询制度时，先检索，不因缺少公司名称而澄清。
已提供金额的普通费用或日常费用审批问题可以查询一般费用权限表；
不同采购或特殊费用规则可在检索后说明适用范围，不必先追问费用类型。
澄清只用于缺失会实质影响判断且无法通过制度说明的必要条件，例如审批问题没有任何金额或假期天数。
话题切换后不要把旧制度问题带入新问题。不能因知识库缺少资料就无休止澄清；问题已明确时检索后如实说明缺少依据。
不知道或不确定的通用事实应如实说明，不声称已联网核实。"""


def plan_reply(settings, text, history, *, classify_only=False, web_search=False):
    system = ROUTING_SYSTEM
    if classify_only:
        system = system.replace(
            '通用问题：{"mode":"general","answer":"正常回答，纯文本，不虚构知识库来源"}。',
            '通用问题：{"mode":"general"}。只判断路由，不生成通用回答。',
        )
    if web_search:
        system += (
            "\n用户已开启联网。仅通用公共问题在 general 中额外返回 query 字段（不超过300字），"
            "作为独立的公共搜索词。不要在 query 中发送完整历史、私有文档、个人资料或凭证。"
            "企业内部制度仍返回 knowledge，缺条件仍返回 clarify；"
            "不得因为联网开关改变企业事实的依据要求。"
        )
    with ModelClient(settings) as model:
        reply = model.complete(
            [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"history": history, "question": text}, ensure_ascii=False
                    ),
                },
            ],
            max_tokens=600 if classify_only else 2200,
            purpose="intent_stream" if classify_only else "intent",
            json_mode=classify_only and settings.llm_provider == "qwen",
        )
    raw = reply.content.strip()
    if raw.startswith("```") and raw.endswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)[:-3].strip()
    try:
        plan = json.loads(raw)
    except (ValueError, TypeError):
        raise ModelProblem("invalid_model_response", "回答格式校验失败，请重试") from None
    if not isinstance(plan, dict) or plan.get("mode") not in ("general", "knowledge", "clarify"):
        raise ModelProblem("invalid_model_response", "回答类型校验失败，请重试")
    # Obvious requests for company-specific facts always require document evidence.
    company_specific = re.search(
        r"我司|本公司|我们公司|咱们公司|本单位|"
        r"(?:公司|企业|单位).{0,20}(?:报销|请假|采购|补贴|工资|薪酬|福利|审批|制度|规定|成立)|"
        r"(?:知识库|文档|手册)(?:中|里)|根据(?:文档|手册|资料)",
        text,
    )
    if company_specific and plan["mode"] == "general":
        return {
            "mode": "knowledge",
            "query": retrieval_question(text, history),
            "decision": "evidence_guard",
        }
    if classify_only and plan["mode"] == "general":
        result = {"mode": "general", "decision": "model"}
        if web_search:
            query = plan.get("query")
            if not isinstance(query, str) or not query.strip() or len(query) > 300:
                raise ModelProblem(
                    "web_query_invalid", "未能生成有效的公共检索问题，请重试", retryable=True
                )
            result["query"] = query.strip()
        return result
    field = "query" if plan["mode"] == "knowledge" else "answer"
    if not isinstance(plan.get(field), str) or not plan[field].strip() or len(plan[field]) > 16000:
        raise ModelProblem("invalid_model_response", "回答内容校验失败，请重试")
    return {"mode": plan["mode"], field: plan[field].strip(), "decision": "model"}


def retrieval_question(text, history):
    previous = next((m["content"] for m in reversed(history) if m["role"] == "user"), None)
    if (
        previous
        and len(text) < 50
        and re.search(r"^(那|那么|如果|这个|那个|它|这项|还有|改成|换成|四天|三天)|呢[？?]?$", text)
    ):
        return f"上一轮问题：{previous}\n当前追问：{text}"
    return text
