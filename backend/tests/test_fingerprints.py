"""Catch filename-based identity and duplicate checks silently accepting bad fingerprints."""

import hashlib

import pytest
from fastapi.testclient import TestClient


def test_fingerprint_depends_on_file_bytes():
    from app.importing.fingerprints import file_fingerprint

    original = "# 制度\n电子发票提交原件。".encode()
    assert file_fingerprint(original) == hashlib.sha256(original).hexdigest()
    assert file_fingerprint(original) != file_fingerprint(original + b"\n")


@pytest.mark.parametrize("value", ["", "a" * 63, "g" * 64, "A" * 64])
def test_duplicate_api_rejects_invalid_fingerprint(value):
    from app.main import create_app

    with TestClient(create_app()) as client:
        result = client.post("/api/documents/check-duplicate", json={"file_sha256": value})
    assert result.status_code == 422


def test_duplicate_api_does_not_report_database_failure_as_no_match():
    from sqlalchemy.exc import OperationalError

    from app.api.documents import get_db
    from app.main import create_app

    class UnavailableDatabase:
        def execute(self, *args, **kwargs):
            raise OperationalError("query", {}, RuntimeError("private-connection-secret"))

    app = create_app()
    app.dependency_overrides[get_db] = lambda: UnavailableDatabase()
    with TestClient(app) as client:
        result = client.post("/api/documents/check-duplicate", json={"file_sha256": "a" * 64})
    assert result.status_code == 503
    assert result.json()["detail"]["code"] == "duplicate_check_unavailable"
    assert "private-connection-secret" not in result.text
