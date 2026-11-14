"""Catch liveness depending on infrastructure and readiness hiding failed dependencies."""

from fastapi.testclient import TestClient


def test_liveness_does_not_require_services():
    from app.config import Settings
    from app.main import create_app

    with TestClient(create_app(Settings(_env_file=None))) as client:
        result = client.get("/api/health/live")
    assert result.status_code == 200
    assert result.json()["status"] == "ok"


def test_readiness_is_503_and_does_not_expose_connection_secrets():
    from app.config import Settings
    from app.main import create_app

    class UnavailableProbe:
        def check(self):
            return {"postgres": False, "redis": True, "rustfs": True, "neo4j": True}

    with TestClient(create_app(Settings(_env_file=None), probe=UnavailableProbe())) as client:
        result = client.get("/api/health/ready")
    assert result.status_code == 503
    assert result.json() == {
        "status": "not_ready",
        "dependencies": {"postgres": False, "redis": True, "rustfs": True, "neo4j": True},
    }


def test_frontend_dev_origin_can_read_health():
    from app.config import Settings
    from app.main import create_app

    with TestClient(create_app(Settings(_env_file=None))) as client:
        result = client.get("/api/health/live", headers={"Origin": "http://127.0.0.1:5174"})
    assert result.headers["access-control-allow-origin"] == "http://127.0.0.1:5174"


def test_unrelated_origin_is_not_allowed():
    from app.config import Settings
    from app.main import create_app

    with TestClient(create_app(Settings(_env_file=None))) as client:
        result = client.get("/api/health/live", headers={"Origin": "https://unrelated.example"})
    assert "access-control-allow-origin" not in result.headers
