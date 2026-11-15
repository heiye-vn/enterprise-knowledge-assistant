from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator


class SessionScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["all", "custom"] = "all"
    document_ids: list[UUID] = []

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        if self.mode == "all" and self.document_ids:
            raise ValueError("全部知识库范围不能附带固定文档清单")
        if self.mode == "custom" and not self.document_ids:
            raise ValueError("自选范围至少需要一份文档")
        if len(self.document_ids) != len(set(self.document_ids)):
            raise ValueError("文档清单不能重复")
        return self


def import_display_status(status: str, stage: str) -> str:
    """Map the unified import state to the approved prototype's progress labels."""
    if status == "queued" and stage in {"queued", "parsing", "chunking", "embedding", "publishing"}:
        if stage == "publishing":
            return "embedding"
        return stage
    if status == "ready" and stage == "done":
        return "ready"
    if status in {"failed", "canceled"}:
        return status
    if status == "running" and stage in {"parsing", "chunking", "embedding", "publishing"}:
        return "embedding" if stage == "publishing" else stage
    raise ValueError(f"Invalid import state: {status}/{stage}")
