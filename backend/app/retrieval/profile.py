import hashlib
import json

from app.config import Settings

INDEX_OPTIONS = {
    "schema_version": 1,
    "max_chars": 1600,
    "overlap_chars": 150,
    "table_context_chars": 6000,
    "max_unit_chars": 24000,
    "batch_size": 20,
}


def embedding_profile(settings: Settings) -> dict:
    return {
        "provider": "aliyun",
        "model": settings.embedding_model,
        "dimension": settings.embedding_dimension,
        "input_format_version": 1,
        "document_type": "document",
        "query_type": "query",
    }


def digest_profile(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()

# 把 heading_path 拼到切片正文前面，补足语义上下文
def embedding_text(content: str, heading_path: list[str]) -> str:
    return (" / ".join(heading_path) + "\n\n" if heading_path else "") + content
