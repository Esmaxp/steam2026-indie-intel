from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.session import engine

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    # A restart kills any sweep this process was running, leaving its row
    # claiming to be live forever. Reconcile on the way in — migration 0014
    # did this once, but a restart happens every deploy.
    #
    # Only in-process runs are cleared. A CLI sweep is a separate process that
    # survives a backend restart; judging it dead here would strand a healthy
    # multi-hour job. Its liveness is judged by heartbeat instead.
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE sweep_jobs SET status='interrupted', paused=false, "
                "active_kind=null, finished_at=now() "
                "WHERE status in ('queued','running','paused') "
                "AND (runner IS NULL OR runner = 'api')"
            )
        )
    yield
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "Discovers, collects, classifies and analyses every Steam indie game "
        "released during 2026. Business metrics always carry a provenance "
        "status: confirmed / estimated / unknown."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["system"])
async def health() -> dict:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        database = "ok"
    except Exception as exc:  # pragma: no cover
        database = f"error: {exc.__class__.__name__}"
    return {"status": "ok" if database == "ok" else "degraded", "database": database}


@app.get("/", tags=["system"])
async def root() -> dict:
    return {
        "name": settings.app_name,
        "docs": "/docs",
        "api": "/api/v1",
        "endpoints": [
            "/api/v1/games",
            "/api/v1/games/{appid}",
            "/api/v1/games/{appid}/stats",
            "/api/v1/dashboard/summary",
            "/api/v1/filters/options",
            "/api/v1/filters/companies",
        ],
    }
