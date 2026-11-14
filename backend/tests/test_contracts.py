"""Catch scope widening, invented pagination, and UI task-state drift."""

from uuid import UUID

import pytest
from pydantic import ValidationError


@pytest.mark.parametrize(
    "value",
    [
        {"mode": "all", "document_ids": ["11111111-1111-4111-8111-111111111111"]},
        {"mode": "custom", "document_ids": []},
        {"mode": "custom", "document_ids": ["not-a-uuid"]},
        {"mode": "custom", "document_ids": ["11111111-1111-4111-8111-111111111111"] * 2},
    ],
)
def test_invalid_scope_is_not_silently_expanded(value):
    from app.contracts import SessionScope

    with pytest.raises(ValidationError):
        SessionScope.model_validate(value)


def test_scope_roundtrip_preserves_selection():
    from app.contracts import SessionScope

    value = SessionScope(mode="custom", document_ids=[UUID("11111111-1111-4111-8111-111111111111")])
    assert value.model_dump(mode="json") == {
        "mode": "custom",
        "document_ids": ["11111111-1111-4111-8111-111111111111"],
    }


@pytest.mark.parametrize(
    ("status", "stage", "expected"),
    [
        ("queued", "queued", "queued"),
        ("running", "parsing", "parsing"),
        ("running", "chunking", "chunking"),
        ("running", "embedding", "embedding"),
        ("running", "publishing", "embedding"),
        ("ready", "done", "ready"),
        ("failed", "parsing", "failed"),
        ("canceled", "embedding", "canceled"),
    ],
)
def test_task_progress_retains_prototype_labels(status, stage, expected):
    from app.contracts import import_display_status

    assert import_display_status(status, stage) == expected


def test_unknown_import_stage_is_not_disguised_as_ready():
    from app.contracts import import_display_status

    with pytest.raises(ValueError):
        import_display_status("running", "extracting")
