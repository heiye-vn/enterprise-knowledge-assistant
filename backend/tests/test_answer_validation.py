import json

import pytest

from app.chat.service import validate_answer
from app.model_clients import ModelProblem

SOURCES = [{"id": "one", "content": "直属主管审批。"}, {"id": "two", "content": "应提前申请。"}]


def test_unused_valid_sources_are_removed_without_inventing_new_citations():
    raw = json.dumps(
        {
            "answerable": True,
            "answer": "由直属主管审批。[1]",
            "citations": [{"source": 1}, {"source": 2}],
        }
    )
    answer, citations, kind = validate_answer(raw, SOURCES)
    assert answer == "由直属主管审批。[1]" and kind == "answered"
    assert [c["citation_no"] for c in citations] == [1]


def test_missing_or_invalid_referenced_source_still_fails_validation():
    for answer, citations in [
        ("未知来源。[3]", [{"source": 1}]),
        ("没有引用", [{"source": 1}]),
        ("正文。[1]", [{"source": 99}]),
    ]:
        with pytest.raises(ModelProblem):
            validate_answer(
                json.dumps({"answerable": True, "answer": answer, "citations": citations}), SOURCES
            )


def test_numeric_reference_entries_are_validated_like_object_entries():
    raw = json.dumps({"answerable": True, "answer": "由直属主管审批。[1]", "citations": [1, 2]})
    _, citations, _ = validate_answer(raw, SOURCES)
    assert [c["citation_no"] for c in citations] == [1]
    for invalid in [True, 99, "1"]:
        with pytest.raises(ModelProblem):
            validate_answer(
                json.dumps({"answerable": True, "answer": "正文。[1]", "citations": [invalid]}),
                SOURCES,
            )
