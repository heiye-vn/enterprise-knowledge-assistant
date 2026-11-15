import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

from app.retrieval.chunking import ChunkingProblem, chunk_document, validate_drafts


def text(identity, value, page=None, heading=None):
    return {
        "block_id": identity,
        "type": "text",
        "text": value,
        "heading_path": heading or ["审批制度"],
        "page_start": page,
        "page_end": page,
    }


def test_same_chapter_can_span_pages_and_ids_are_stable_per_generation():
    job = uuid4()
    blocks = [text("a", "第八条 报销应提交发票。", 1), text("b", "并附部门负责人审批记录。", 2)]
    chunks = chunk_document(job, blocks)
    assert len(chunks) == 1
    assert chunks[0].page_start == 1 and chunks[0].page_end == 2
    assert "发票" in chunks[0].content and "审批记录" in chunks[0].content
    assert chunks == chunk_document(job, blocks)
    assert chunks[0].id != chunk_document(uuid4(), blocks)[0].id
    validate_drafts(blocks, chunks)


def test_long_text_coverage_and_overlap_never_lose_source_characters():
    value = "".join(f"第{i}项条件：金额{i}元，由主管审批。" for i in range(60))
    blocks = [text("long", value)]
    chunks = chunk_document(uuid4(), blocks, max_chars=180, overlap_chars=30)
    covered = set()
    for chunk in chunks:
        assert len(chunk.content) <= 180 and chunk.page_start is None
        for locator in chunk.locators:
            covered.update(range(locator["start"], locator["end"]))
            assert value[locator["start"] : locator["end"]] in chunk.content
    assert covered == set(range(len(value)))
    assert sum(len(c.content) for c in chunks) > len(value)


def test_heading_boundaries_do_not_merge_unrelated_sections():
    blocks = [text("a", "报销条款", heading=["财务"]), text("b", "请假条款", heading=["人事"])]
    chunks = chunk_document(uuid4(), blocks)
    assert [c.heading_path for c in chunks] == [["财务"], ["人事"]]


def test_real_approval_table_keeps_amounts_roles_and_applicability_context():
    blocks = json.loads(
        Path(__file__).with_name("fixtures").joinpath("approval-blocks.json").read_text(
            encoding="utf-8"
        )
    )
    chunks = chunk_document(uuid4(), blocks, max_chars=300, overlap_chars=30)
    table_chunks = [c for c in chunks if any("row_start" in loc for loc in c.locators)]
    assert table_chunks
    for chunk in table_chunks:
        assert "单笔/单事项预计金额" in chunk.content and "审批链" in chunk.content
        assert "采购申请" in chunk.content and "不适用本条" in chunk.content
    combined = "\n".join(c.content for c in table_chunks)
    assert all(
        value in combined
        for value in ["1,000", "5,000", "20,000", "直属主管", "财务经理", "总经理"]
    )
    assert all(c.page_start is None and c.page_end is None for c in chunks)
    validate_drafts(blocks, chunks)


def test_rowspan_conditions_stay_with_every_dependent_row():
    rows = [
        [{"text": "金额", "header": True}, {"text": "审批条件", "header": True}],
        [{"text": "预算内", "rowspan": 2}, {"text": "1000元由主管审批"}],
        [{"text": "5000元由部门负责人审批"}],
        [{"text": "预算外另行报批"}],
    ]
    block = {
        **text("table", "placeholder"),
        "type": "table",
        "rows": rows,
        "captions": [],
        "footnotes": ["禁止拆单规避审批"],
    }
    chunks = chunk_document(uuid4(), [block], max_chars=35, overlap_chars=5)
    for chunk in chunks:
        if "1000元" in chunk.content or "5000元" in chunk.content:
            assert (
                "1000元" in chunk.content
                and "5000元" in chunk.content
                and "预算内" in chunk.content
            )
        assert "禁止拆单" in chunk.content


def test_tampered_content_or_locator_is_rejected_before_embedding():
    blocks = [text("original", "真实原文")]
    chunks = chunk_document(uuid4(), blocks)
    chunks[0].content += "伪造审批条件"
    with pytest.raises(ChunkingProblem):
        validate_drafts(blocks, chunks)
    chunks = chunk_document(uuid4(), blocks)
    chunks[0].locators[0]["block_id"] = "missing"
    with pytest.raises(ChunkingProblem):
        validate_drafts(blocks, chunks)


def test_duplicate_block_identity_and_fake_page_ranges_are_rejected():
    with pytest.raises(ChunkingProblem):
        chunk_document(uuid4(), [text("same", "一"), text("same", "二")])
    block = deepcopy(text("bad", "内容", 0))
    with pytest.raises(ChunkingProblem):
        chunk_document(uuid4(), [block])
