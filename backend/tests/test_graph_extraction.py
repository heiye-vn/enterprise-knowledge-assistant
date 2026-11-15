import json
from dataclasses import asdict
from uuid import uuid4

import pytest

from app.graph.extraction import build_units, validate_response
from app.importing.parsing import parse_markdown
from app.retrieval.chunking import chunk_document


def units_from(markdown, table_footnote=None):
    parsed = parse_markdown(markdown.encode())
    if table_footnote:
        next(block for block in parsed.blocks if block["type"] == "table")["footnotes"] = [
            table_footnote
        ]
    chunks = chunk_document(uuid4(), parsed.blocks)
    sources = [
        {
            **asdict(chunk),
            "id": str(chunk.id),
            "document_id": str(uuid4()),
            "document_title": "考勤制度",
            "version_id": str(uuid4()),
            "job_id": str(uuid4()),
            "filename": "考勤.md",
            "format": "md",
            "file_url": "/file",
            "version_no": 1,
            "generation_no": 1,
        }
        for chunk in chunks
    ]
    return build_units(parsed.blocks, sources)


def response_for(unit, **changes):
    value = {
        "unit_id": unit.id,
        "title": "请假审批与备案",
        "conditions": [unit.text],
        "relations": [
            {"type": "approved_by", "target": "直属主管"},
            {"type": "recorded_by", "target": "人力资源部"},
        ],
    }
    return json.dumps({"rules": [{**value, **changes}]}, ensure_ascii=False)


def test_approval_and_filing_keep_distinct_types_and_verbatim_conditions():
    unit = units_from(
        "## 请假\n\n超过3个工作日，由直属主管审批，人力资源部仅备案，不替代前述业务审批。"
    )[0]
    accepted, rejected = validate_response(response_for(unit), [unit])
    assert not rejected and accepted[0]["quote"] == unit.text
    assert [(r["type"], r["target_kind"]) for r in accepted[0]["relations"]] == [
        ("approved_by", "role"),
        ("recorded_by", "role"),
    ]
    assert "超过3个工作日" in "".join(accepted[0]["conditions"])


@pytest.mark.parametrize(
    "changes",
    [
        {"conditions": []},
        {"conditions": ["超过3天就行"]},
        {"title": "10天请假审批"},
        {"relations": [{"type": "approved_by", "target": "总经理"}]},
        {"relations": [{"type": "approved_by", "target": "人力资源部"}]},
        {"relations": [{"type": "arbitrary_cypher", "target": "直属主管"}]},
        {"unit_id": "unknown-source"},
    ],
)
def test_unsupported_facts_cannot_become_graph_relations(changes):
    unit = units_from(
        "## 请假\n\n超过3个工作日，由直属主管审批，人力资源部仅备案，不替代前述业务审批。"
    )[0]
    accepted, rejected = validate_response(response_for(unit, **changes), [unit])
    assert not accepted and rejected


def test_temporal_and_hour_conditions_cannot_be_silently_lost():
    unit = units_from("## 远程办公\n\n远程办公应事前取得直属主管批准，最小申请单位为0.5小时。")[0]
    accepted, rejected = validate_response(
        response_for(
            unit,
            conditions=["最小申请单位为0.5小时"],
            relations=[{"type": "approved_by", "target": "直属主管"}],
        ),
        [unit],
    )
    assert not accepted and rejected


def test_table_scope_keeps_both_money_boundaries_without_mixing_rows():
    units = units_from(
        "## 报销\n\n| 金额 | 审批 |\n| --- | --- |\n| 超过5,000"
        "元且不超过20,000元 | 财务经理审批 |\n| 超过20,000元 | 总经理审批 |"
    )
    table = [unit for unit in units if unit.scope]
    assert len(table) == 2
    first = table[0]
    accepted, rejected = validate_response(
        response_for(
            first,
            title="报销审批",
            conditions=[],
            relations=[{"type": "approved_by", "target": "财务经理"}],
        ),
        [first],
    )
    assert not rejected and accepted[0]["scope"] == "超过5,000元且不超过20,000元"
    accepted, rejected = validate_response(
        response_for(
            first, title="报销审批", relations=[{"type": "approved_by", "target": "总经理"}]
        ),
        [first],
    )
    assert not accepted and rejected


def test_merged_table_rows_remain_atomic_and_repeatable():
    text = (
        '## 规则\n\n<table><tr><th>条件</th><th>材料</th></tr><tr><td rowspan="2">外勤</td>'
        "<td>审批单</td></tr><tr><td>签到记录</td></tr></table>"
    )
    first = units_from(text)
    assert first and all(unit.source["locators"] for unit in first)
    assert any("审批单" in unit.text and "签到记录" in unit.text for unit in first)


def test_empty_valid_response_is_honest_and_invalid_json_is_rejected():
    assert validate_response('{"rules":[]}', []) == ([], [])
    with pytest.raises(ValueError):
        validate_response("模型自由文本，不能作为已校验结果", [])


def test_table_footnote_limits_are_part_of_the_validated_evidence():
    unit = units_from(
        "# 请假\n\n| 时长 | 审批 |\n| --- | --- |\n| 不超过1个工作日 | 直属主管审批 |",
        table_footnote="紧急情况下不得跳过审批。",
    )[0]
    assert "不得跳过审批" in unit.text
    accepted, rejected = validate_response(
        response_for(
            unit, conditions=[], relations=[{"type": "approved_by", "target": "直属主管"}]
        ),
        [unit],
    )
    assert not accepted and rejected


def test_graph_scope_filters_numeric_boundaries_without_converting_hours_to_days():
    from app.retrieval.graph_expansion import scope_matches

    assert scope_matches("员工请半天事假", "不超过1个工作日") is True
    assert scope_matches("员工请半天事假", "超过1个且不超过3个工作日") is False
    assert scope_matches("请假3个工作日", "超过3个工作日") is False
    assert scope_matches("报销5000元", ">1,000元且≤5,000元") is True
    assert scope_matches("报销5000元", ">5,000元且≤20,000元") is False
    assert scope_matches("请假4小时", "不超过1个工作日") is None
    assert scope_matches("请假超过3个工作日", "超过3个工作日") is None
