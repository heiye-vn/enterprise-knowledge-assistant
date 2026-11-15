"""Deterministic chunks whose contents can be reconstructed from source locators."""

import hashlib
import re
from dataclasses import dataclass
from uuid import UUID, uuid5

from app.importing.parsing import rows_text


class ChunkingProblem(ValueError):
    pass


@dataclass
class ChunkDraft:
    id: UUID
    ordinal: int
    content: str
    content_sha256: str
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    locators: list[dict]


def source_map(blocks):
    mapped = {}
    for block in blocks:
        identity = block.get("block_id")
        if not isinstance(identity, str) or not identity or identity in mapped:
            raise ChunkingProblem("内容块标识缺失或重复")
        first, last = block.get("page_start"), block.get("page_end")
        if not (first is None and last is None) and not (
            type(first) is int and type(last) is int and 1 <= first <= last
        ):
            raise ChunkingProblem("内容块页码无效")
        if not isinstance(block.get("text"), str) or not isinstance(
            block.get("heading_path"), list
        ):
            raise ChunkingProblem("内容块正文或章节无效")
        mapped[identity] = block
    return mapped


def locate_text(block, start=0, end=None):
    return {
        "block_id": block["block_id"],
        "start": start,
        "end": len(block["text"]) if end is None else end,
    }


def source_text(mapped, locator):
    block = mapped.get(locator.get("block_id"))
    if block is None:
        raise ChunkingProblem("切片引用了不存在的内容块")
    if "row_start" in locator:
        rows = block.get("rows", [])
        start, end, header = (
            locator["row_start"],
            locator.get("row_end"),
            locator.get("header_rows"),
        )
        if any(
            type(v) is not int for v in [start, end, header]
        ) or not 0 <= header <= start <= end <= len(rows):
            raise ChunkingProblem("切片表格行范围无效")
        selected = [*rows[:header], *rows[start:end]]
        return "\n".join(
            [*block.get("captions", []), rows_text(selected), *block.get("footnotes", [])]
        ).strip()
    start, end = locator.get("start"), locator.get("end")
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(block["text"]):
        raise ChunkingProblem("切片字符范围无效")
    return block["text"][start:end]


def page_range(mapped, locators):
    ranges = [
        (mapped[x["block_id"]].get("page_start"), mapped[x["block_id"]].get("page_end"))
        for x in locators
    ]
    if any(start is None for start, _ in ranges):
        return None, None
    return min(x[0] for x in ranges), max(x[1] for x in ranges)


def text_parts(block, max_chars, overlap):
    text = block["text"]
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            boundaries = list(re.finditer(r"[。！？；\n]", text[start:end]))
            if boundaries and boundaries[-1].end() >= max_chars // 2:
                end = start + boundaries[-1].end()
        if text[start:end].strip():
            yield locate_text(block, start, end)
        if end == len(text):
            break
        start = max(start + 1, end - overlap)


def table_groups(rows, header):
    start = header
    while start < len(rows):
        end = start + 1
        index = start
        # A rowspan can transitively link several rows; the whole group is atomic.
        while index < end:
            for cell in rows[index]:
                span = cell.get("rowspan", 1)
                if type(span) is not int or span < 1:
                    raise ChunkingProblem("表格合并行范围无效")
                end = max(end, min(len(rows), index + span))
            index += 1
        yield start, end
        start = end


def table_parts(block, mapped, max_chars):
    rows = block.get("rows")
    if not rows:
        yield locate_text(block)
        return
    header = 1
    while header < len(rows) and all(cell.get("header", False) for cell in rows[header]):
        header += 1
    groups = list(table_groups(rows, header)) or [(header, header)]
    first, last = groups[0]
    for start, end in groups[1:]:
        candidate = {
            "block_id": block["block_id"],
            "row_start": first,
            "row_end": end,
            "header_rows": header,
        }
        if len(source_text(mapped, candidate)) > max_chars:
            yield {**candidate, "row_end": last}
            first = start
        last = end
    yield {
        "block_id": block["block_id"],
        "row_start": first,
        "row_end": last,
        "header_rows": header,
    }


def chunk_document(
    job_id: UUID,
    blocks: list[dict],
    *,
    max_chars=1600,
    overlap_chars=150,
    table_context_chars=6000,
    max_unit_chars=24000,
) -> list[ChunkDraft]:
    if max_chars < 20 or not 0 <= overlap_chars < max_chars // 2:
        raise ChunkingProblem("切片长度或重叠范围无效")
    mapped = source_map(blocks)
    chunks, pending = [], []
    pending_heading = []

    def append(locators, heading):
        if not locators:
            return
        value = "\n\n".join(source_text(mapped, x) for x in locators)
        if not value.strip():
            return
        if len(value) > max_unit_chars:
            raise ChunkingProblem("单个条款或合并表格过长，无法安全切分")
        first, last = page_range(mapped, locators)
        ordinal = len(chunks)
        chunks.append(
            ChunkDraft(
                uuid5(job_id, f"chunk-v1:{ordinal}"),
                ordinal,
                value,
                hashlib.sha256(value.encode()).hexdigest(),
                list(heading),
                first,
                last,
                locators,
            )
        )

    for i, block in enumerate(blocks):
        if not block["text"].strip() or block.get("type") == "heading":
            continue
        heading = block["heading_path"]
        if block.get("type") == "table":
            append(pending, pending_heading)
            pending = []
            before, after = [], []
            for offset, target in [(-1, before), (1, after)]:
                if 0 <= i + offset < len(blocks):
                    neighbor = blocks[i + offset]
                    if (
                        neighbor.get("type") in {"text", "list"}
                        and neighbor["heading_path"] == heading
                        and 0 < len(neighbor["text"]) <= table_context_chars
                    ):
                        target.append(locate_text(neighbor))
            for locator in table_parts(block, mapped, max_chars):
                append([*before, locator, *after], heading)
            continue
        for locator in text_parts(block, max_chars, overlap_chars):
            value = source_text(mapped, locator)
            if pending and (
                heading != pending_heading
                or len(value) + sum(len(source_text(mapped, x)) + 2 for x in pending) > max_chars
            ):
                append(pending, pending_heading)
                pending = []
            pending.append(locator)
            pending_heading = heading
    append(pending, pending_heading)
    if not chunks:
        raise ChunkingProblem("解析结果没有可检索正文")
    validate_drafts(blocks, chunks)
    return chunks


def validate_drafts(blocks, drafts):
    mapped = source_map(blocks)
    ids = set()
    for ordinal, draft in enumerate(drafts):
        if draft.ordinal != ordinal or draft.id in ids or not draft.locators:
            raise ChunkingProblem("切片序号或标识无效")
        ids.add(draft.id)
        expected = "\n\n".join(source_text(mapped, x) for x in draft.locators)
        if (
            expected != draft.content
            or hashlib.sha256(expected.encode()).hexdigest() != draft.content_sha256
        ):
            raise ChunkingProblem("切片内容与解析原文不一致")
        if (draft.page_start, draft.page_end) != page_range(mapped, draft.locators):
            raise ChunkingProblem("切片页码与来源不一致")
        if any(mapped[x["block_id"]]["heading_path"] != draft.heading_path for x in draft.locators):
            raise ChunkingProblem("切片章节与来源不一致")
