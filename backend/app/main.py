from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import Settings
from app.infrastructure import DependencyProbe


def create_app(settings: Settings | None = None, *, probe=None) -> FastAPI:
    settings = settings or Settings()
    probe = probe or DependencyProbe(settings)
    app = FastAPI(title="企业知识助理", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @app.get("/api/health/live", tags=["health"])
    def live():
        return {"status": "ok", "service": settings.service_name}

    @app.get("/api/health/ready", tags=["health"])
    def ready():
        dependencies = probe.check()
        healthy = bool(dependencies) and all(dependencies.values())
        return JSONResponse(
            {"status": "ready" if healthy else "not_ready", "dependencies": dependencies},
            status_code=200 if healthy else 503,
        )

    return app


app = create_app()
