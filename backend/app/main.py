from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.chat import router as chat_router
from app.api.documents import files_router
from app.api.documents import router as documents_router
from app.api.graph import router as graph_router
from app.api.jobs import router as jobs_router
from app.api.parsing import router as parsing_router
from app.api.search import router as search_router
from app.chat.streaming import ChatStreams
from app.config import Settings
from app.db import create_db_engine, session_factory
from app.infrastructure import DependencyProbe


def create_app(settings: Settings | None = None, *, probe=None) -> FastAPI:
    settings = settings or Settings()
    probe = probe or DependencyProbe(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = create_db_engine(settings)
        app.state.db_sessions = session_factory(engine)
        app.state.db_engine = engine
        app.state.chat_streams = ChatStreams(engine, settings)
        try:
            yield
        finally:
            app.state.chat_streams.shutdown()
            engine.dispose()

    app = FastAPI(title="企业知识助理", version="0.1.0", lifespan=lifespan)
    app.include_router(documents_router)
    app.include_router(files_router)
    app.include_router(jobs_router)
    app.include_router(parsing_router)
    app.include_router(search_router)
    app.include_router(chat_router)
    app.include_router(graph_router)
    app.state.settings = settings
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
