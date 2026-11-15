import io
import json
import zipfile
from pathlib import Path

import pytest

from app.importing.archive import read_archive
from app.importing.parsing import ParseError, parse_markdown


def archive(entries):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, value in entries:
            z.writestr(name, value)
    return out.getvalue()


@pytest.mark.parametrize("format", ["png", "jpg"])
def test_image_ocr_has_one_real_original_page(format):
    data = archive(
        [
            ("full.md", "# 报销指引\n普通费用应在10个工作日内提交。"),
            (
                "image_content_list.json",
                json.dumps(
                    [{"type": "text", "text": "普通费用应在10个工作日内提交。", "page_idx": 0}]
                ),
            ),
        ]
    )
    result = read_archive(data, format)
    assert result.page_count == 1
    assert result.blocks[0]["page_start"] == result.blocks[0]["page_end"] == 1


def test_markdown_preserves_headings_table_conditions_code_and_no_invented_pages():
    result = parse_markdown(
        "# 报销制度\n\n## 审批\n\n不超过 500 元由主管审批。\n\n"
        "| 金额 | 岗位 | 条件 |\n| --- | --- | --- |\n| 500 元 | 主管 | 含税 |\n\n"
        '```python\nprint("<safe>")\n```\n'.encode()
    )
    assert result.page_count is None
    table = next(b for b in result.blocks if b["type"] == "table")
    assert table["heading_path"] == ["报销制度", "审批"]
    assert table["rows"][0][0]["text"] == "金额"
    assert table["rows"][1][2]["text"] == "含税"
    assert "500 元" in table["text"]
    assert all(b["page_start"] is None and b["page_end"] is None for b in result.blocks)
    assert next(b for b in result.blocks if b["type"] == "code")["text"] == 'print("<safe>")\n'
    assert result.blocks == parse_markdown(result.markdown.encode()).blocks


def test_mineru_archive_preserves_real_pages_table_spans_captions_and_image():
    items = [
        {"type": "text", "text": "采购", "text_level": 1, "page_idx": 0},
        {
            "type": "table",
            "table_body": (
                '<table><tr><th colspan="2">金额</th></tr>'
                "<tr><td>1000</td><td>含税</td></tr></table>"
            ),
            "table_caption": ["审批表"],
            "table_footnote": ["紧急采购例外"],
            "page_idx": 1,
        },
        {"type": "image", "img_path": "images/one.png", "image_caption": ["流程图"], "page_idx": 1},
    ]
    data = archive(
        [
            ("full.md", "# 采购\n审批表"),
            ("doc_content_list.json", json.dumps(items)),
            ("images/one.png", b"\x89PNG\r\n\x1a\nimage"),
        ]
    )
    result = read_archive(data, "pdf")
    assert result.blocks[0]["page_start"] == 1
    table = result.blocks[1]
    assert table["page_start"] == table["page_end"] == 2
    assert table["rows"][0][0]["colspan"] == 2
    assert all(x in table["text"] for x in ["金额", "1000", "含税", "审批表", "紧急采购例外"])
    image = result.blocks[2]
    assert image["asset_id"] in result.assets
    assert result.assets[image["asset_id"]].content.startswith(b"\x89PNG")
    assert read_archive(data, "docx").blocks[1]["page_start"] is None


@pytest.mark.parametrize("name", ["../escape", "/absolute", "images\\bad.png", "a/../bad"])
def test_archive_rejects_unsafe_paths(name):
    with pytest.raises(ParseError):
        read_archive(archive([("full.md", "ok"), (name, "bad")]), "pdf")


def test_archive_rejects_expansion_limit_and_missing_structured_content():
    with pytest.raises(ParseError):
        read_archive(archive([("full.md", "a" * 200)]), "pdf", max_uncompressed=100)
    with pytest.raises(ParseError):
        read_archive(archive([("full.md", "text only")]), "pdf")


def test_archive_ignores_script_in_table_and_keeps_unknown_content_as_text():
    entries = [
        {
            "type": "table",
            "table_body": "<table><tr><td>金额<script>alert(1)</script></td></tr></table>",
        },
        {"type": "equation", "text": "a+b"},
    ]
    result = read_archive(
        archive([("full.md", "ok"), ("x_content_list.json", json.dumps(entries))]), "pdf"
    )
    assert result.blocks[0]["rows"][0][0]["text"] == "金额"
    assert result.blocks[1]["text"] == "a+b"


@pytest.mark.parametrize("format", ["pdf", "docx"])
def test_real_cloud_fixture_preserves_table_fields_and_locations(format):
    content = (
        Path(__file__).with_name("fixtures").joinpath(f"mineru-{format}-content.json").read_bytes()
    )
    result = read_archive(
        archive([("full.md", "云端结构夹具"), ("doc_content_list.json", content)]), format
    )
    table = next(b for b in result.blocks if b["type"] == "table")
    assert "制度编号" in table["text"] and "版本号" in table["text"]
    assert "2026年11月" in table["text"]
    assert table["page_start"] == (1 if format == "pdf" else None)


def test_malformed_table_is_a_controlled_parse_error():
    with pytest.raises(ParseError):
        read_archive(
            archive(
                [("full.md", "bad"), ("x_content_list.json", '[{"type":"table","table_body":123}]')]
            ),
            "pdf",
        )


@pytest.mark.parametrize("page", [1, False, {}])
def test_image_ocr_rejects_nonexistent_or_malformed_pages(page):
    data = archive(
        [
            ("full.md", "图片正文"),
            (
                "image_content_list.json",
                json.dumps([{"type": "text", "text": "图片正文", "page_idx": page}]),
            ),
        ]
    )
    with pytest.raises(ParseError):
        read_archive(data, "png")
