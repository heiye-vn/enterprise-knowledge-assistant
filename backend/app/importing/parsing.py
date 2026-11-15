"""Provider-independent blocks, with honest locations and safe structured tables."""

import hashlib
from dataclasses import dataclass, field
from html.parser import HTMLParser

from markdown_it import MarkdownIt


class ParseError(ValueError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code, self.retryable = code, retryable


@dataclass
class Asset:
    content: bytes
    mime_type: str
    name: str


@dataclass
class ParsedDocument:
    markdown: str
    blocks: list[dict]
    assets: dict[str, Asset] = field(default_factory=dict)
    page_count: int | None = None


def block(ordinal: int, kind: str, text: str, headings: list[str], page=None, **extra):
    return {
        "block_id": f"b{ordinal:06d}",
        "type": kind,
        "text": text,
        "heading_path": list(headings),
        "page_start": page,
        "page_end": page,
        **extra,
    }


def content_hash(markdown: str) -> str:
    return hashlib.sha256(markdown.encode()).hexdigest()


class TableReader(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.row, self.cell = [], None, None
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1
        if self.skip:
            return
        if tag == "tr":
            self.row = []
            self.rows.append(self.row)
        if tag in {"td", "th"}:
            if self.row is None:
                self.row = []
                self.rows.append(self.row)
            values = dict(attrs)

            def span(key):
                try:
                    return max(1, min(100, int(values.get(key, 1))))
                except (ValueError, TypeError):
                    return 1

            self.cell = {
                "text": "",
                "header": tag == "th",
                "colspan": span("colspan"),
                "rowspan": span("rowspan"),
            }
            self.row.append(self.cell)
        if tag == "br" and self.cell is not None:
            self.cell["text"] += "\n"

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skip = max(0, self.skip - 1)
        if tag in {"td", "th"}:
            if self.cell is not None:
                self.cell["text"] = self.cell["text"].strip()
            self.cell = None
        if tag == "tr":
            self.row = None

    def handle_data(self, value):
        if self.cell is not None and not self.skip:
            self.cell["text"] += value


def table_rows(html: str) -> list[list[dict]]:
    if not isinstance(html, str):
        raise ParseError("invalid_archive", "解析表格格式无效")
    reader = TableReader()
    reader.feed(html)
    return reader.rows


def rows_text(rows: list[list[dict]]) -> str:
    return "\n".join(" | ".join(c["text"] for c in row) for row in rows)


def parse_markdown(content: bytes) -> ParsedDocument:
    try:
        markdown = content.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError:
        raise ParseError("invalid_markdown", "Markdown 必须使用 UTF-8 编码") from None
    tokens = MarkdownIt("commonmark").enable("table").parse(markdown)
    blocks, headings = [], []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.type == "heading_open":
            level = int(token.tag[1:])
            text = tokens[i + 1].content
            headings = headings[: level - 1] + [text]
            blocks.append(block(len(blocks), "heading", text, headings, level=level))
            i += 3
            continue
        if token.type == "table_open":
            rows, row = [], None
            i += 1
            header = False
            while i < len(tokens) and tokens[i].type != "table_close":
                t = tokens[i]
                if t.type == "tr_open":
                    row = []
                    rows.append(row)
                elif t.type in {"th_open", "td_open"}:
                    header = t.type == "th_open"
                elif t.type == "inline" and row is not None:
                    row.append({"text": t.content, "header": header, "colspan": 1, "rowspan": 1})
                i += 1
            blocks.append(block(len(blocks), "table", rows_text(rows), headings, rows=rows))
        elif token.type in {"fence", "code_block"}:
            blocks.append(block(len(blocks), "code", token.content, headings))
        elif token.type == "inline" and token.content.strip():
            blocks.append(block(len(blocks), "text", token.content, headings))
        elif token.type == "html_block" and token.content.strip():
            # Retain source as escaped text, never executable HTML.
            blocks.append(block(len(blocks), "text", token.content, headings))
        i += 1
    if not blocks:
        raise ParseError("empty_document", "文档没有可解析的正文")
    return ParsedDocument(markdown, blocks)
