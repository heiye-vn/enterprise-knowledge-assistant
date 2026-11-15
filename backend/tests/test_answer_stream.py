import json

import pytest


@pytest.mark.parametrize("width", [1, 2, 5, 17, 200])
def test_answer_text_decodes_incrementally_without_leaking_json_or_nested_fields(width):
    from app.chat.answer_stream import AnswerDecoder

    text = '你好\n引用[1]，引号"和反斜线\\，😀。'
    raw = json.dumps(
        {
            "metadata": {"answer": "不得显示"},
            "answerable": True,
            "answer": text,
            "citations": [{"source": 1}],
        },
        ensure_ascii=True,
    )
    decoder = AnswerDecoder()
    pieces = [decoder.feed(raw[i : i + width]) for i in range(0, len(raw), width)]
    assert "".join(pieces) == text
    assert all(text.startswith("".join(pieces[: i + 1])) for i in range(len(pieces)))
    if width < 17:
        assert sum(bool(piece) for piece in pieces) > 1


def test_refusal_without_answer_text_never_streams_json_as_prose():
    from app.chat.answer_stream import AnswerDecoder

    assert AnswerDecoder().feed('{"answerable":false}') == ""


def test_duplicate_answer_fields_are_rejected_instead_of_changing_visible_text():
    from app.chat.answer_stream import AnswerDecoder

    decoder = AnswerDecoder()
    assert decoder.feed('{"answer":"草稿"') == "草稿"
    with pytest.raises(ValueError):
        decoder.feed(',"answer":"替换答案"}')
