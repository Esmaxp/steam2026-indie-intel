from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.session import engine

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
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
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
        "phase": "1 — architecture & database",
        "docs": "/docs",
        "api": "/api/v1 (arrives in Phase 5)",
    }
