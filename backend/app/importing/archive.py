"""Read bounded MinerU archives in memory; never extract provider paths to disk."""

import hashlib
import io
import json
import stat
import zipfile
from pathlib import PurePosixPath

from app.importing.parsing import Asset, ParsedDocument, ParseError, block, rows_text, table_rows


def safe_path(name: str) -> bool:
    return bool(name) and not (
        "\\" in name
        or "\x00" in name
        or ":" in name
        or name.startswith("/")
        or any(p in {"..", ".", ""} for p in name.rstrip("/").split("/"))
    )


def read_archive(
    content: bytes, format: str, *, max_uncompressed=100 * 1024 * 1024, max_members=2000
) -> ParsedDocument:
    if len(content) > 50 * 1024 * 1024:
        raise ParseError("archive_too_large", "解析归档超过大小限制")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            entries = z.infolist()
            if len(entries) > max_members or sum(x.file_size for x in entries) > max_uncompressed:
                raise ParseError("archive_too_large", "解析归档超过解压限制")
            names = set()
            for item in entries:
                if (
                    not safe_path(item.filename)
                    or item.filename in names
                    or stat.S_ISLNK(item.external_attr >> 16)
                    or item.flag_bits & 1
                ):
                    raise ParseError("unsafe_archive", "解析归档包含无效路径或重复成员")
                names.add(item.filename)
            md = [n for n in names if PurePosixPath(n).name == "full.md"]
            structured = [n for n in names if n.endswith("_content_list.json")]
            if len(md) != 1 or len(structured) != 1:
                raise ParseError("invalid_archive", "解析归档缺少唯一的正文或结构化内容列表")
            markdown = z.read(md[0]).decode("utf-8-sig")
            items = json.loads(z.read(structured[0]))
            if not isinstance(items, list) or len(items) > 50000:
                raise ParseError("invalid_archive", "解析内容列表格式无效")
            return normalize(items, markdown, z, PurePosixPath(structured[0]).parent, format)
    except (zipfile.BadZipFile, UnicodeError, json.JSONDecodeError, KeyError, RuntimeError):
        raise ParseError("invalid_archive", "无法读取 MinerU 解析归档") from None


def normalize(items, markdown, z, base, format):
    blocks, assets, headings = [], {}, []
    names = set(z.namelist())
    for item in items:
        if not isinstance(item, dict):
            raise ParseError("invalid_archive", "解析内容块格式无效")
        kind, text = item.get("type", "text"), item.get("text", "")
        if not isinstance(kind, str):
            raise ParseError("invalid_archive", "解析内容块类型无效")
        text = text if isinstance(text, str) else ""
        page_idx = item.get("page_idx")
        if format in {"png", "jpg"}:
            if page_idx is not None and (type(page_idx) is not int or page_idx != 0):
                raise ParseError("invalid_page_location", "单张图片解析结果包含无效页码")
            page = 1
        else:
            page = (
                page_idx + 1
                if format == "pdf" and type(page_idx) is int and page_idx >= 0
                else None
            )
        extra = {}
        level = item.get("text_level")
        if type(level) is int and level > 0:
            level = min(level, 6)
            headings = headings[: level - 1] + [text]
            kind, extra = "heading", {"level": level}
        elif kind == "table":
            rows = table_rows(item.get("table_body") or "")
            captions = strings(item.get("table_caption"))
            footnotes = strings(item.get("table_footnote"))
            text = "\n".join([*captions, rows_text(rows), *footnotes]).strip()
            extra = {"rows": rows, "captions": captions, "footnotes": footnotes}
        elif kind == "image":
            captions = strings(item.get("image_caption"))
            footnotes = strings(item.get("image_footnote"))
            text = "\n".join([*captions, *footnotes])
            path = item.get("img_path", "")
            if not isinstance(path, str):
                raise ParseError("invalid_archive", "解析图片路径格式无效")
            if path and safe_path(path):
                name = str(base / path)
                if name in names:
                    data = z.read(name)
                    mime = image_mime(data)
                    if mime:
                        asset_id = hashlib.sha256(name.encode()).hexdigest()[:24]
                        assets[asset_id] = Asset(data, mime, PurePosixPath(path).name)
                        extra = {"asset_id": asset_id}
        elif kind in {"equation", "interline_equation"}:
            kind = "formula"
        elif kind not in {"code", "text", "list"}:
            kind = "text"
        if kind == "list":
            text = "\n".join(strings(item.get("list_items"))) or text
        blocks.append(block(len(blocks), kind, text, headings, page, **extra))
    if not blocks or not markdown.strip():
        raise ParseError("empty_document", "解析服务未返回正文")
    return ParsedDocument(
        markdown, blocks, assets, page_count=1 if format in {"png", "jpg"} else None
    )


def strings(value):
    if isinstance(value, str):
        return [value]
    if value is None:
        return []
    if not isinstance(value, list):
        raise ParseError("invalid_archive", "解析内容列表格式无效")
    return [v for v in value if isinstance(v, str)]


def image_mime(content):
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None
