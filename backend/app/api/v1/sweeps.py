"""Admin endpoints for on-demand collector runs (X-Admin-Token header).

  POST   /admin/sweeps            start a run
  GET    /admin/sweeps            recent runs with live progress
  POST   /admin/sweeps/{id}/cancel
"""

import datetime

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.videos import require_admin
from app.db.session import get_db
from app.models import SWEEP_KINDS, SweepJob
from app.services import sweeps

router = APIRouter(dependencies=[Depends(require_admin)])

MAX_LISTED = 20


class SweepRequest(BaseModel):
    kinds: list[str] = Field(..., min_length=1)
    # Release-date window: which GAMES to scan. Omit both for the whole
    # catalogue. The rank sweep ignores these — it reads one global chart.
    release_from: datetime.date | None = None
    release_to: datetime.date | None = None
    # 0 / null = no cap. Useful for a quick trial run before a multi-hour one.
    limit_per_kind: int | None = Field(default=None, ge=0)

    @field_validator("kinds")
    @classmethod
    def known_kinds(cls, value: list[str]) -> list[str]:
        unknown = [k for k in value if k not in SWEEP_KINDS]
        if unknown:
            raise ValueError(f"unknown sweep kind(s): {', '.join(unknown)}")
        # Preserve the canonical order and drop duplicates: rank is quick, so
        # it runs first and the UI shows a result within minutes.
        return [k for k in SWEEP_KINDS if k in value]


class SweepOut(BaseModel):
    id: int
    kinds: list[str]
    release_from: datetime.date | None = None
    release_to: datetime.date | None = None
    limit_per_kind: int | None = None
    status: str
    cancel_requested: bool
    created_at: datetime.datetime
    started_at: datetime.datetime | None = None
    finished_at: datetime.datetime | None = None
    progress: dict = {}
    error: str | None = None


def _out(job: SweepJob) -> SweepOut:
    return SweepOut(
        id=job.id, kinds=list(job.kinds), release_from=job.release_from,
        release_to=job.release_to, limit_per_kind=job.limit_per_kind,
        status=job.status, cancel_requested=job.cancel_requested,
        created_at=job.created_at, started_at=job.started_at,
        finished_at=job.finished_at, progress=job.progress or {}, error=job.error,
    )


@router.post("/sweeps", response_model=SweepOut, status_code=202)
async def start_sweep(body: SweepRequest, db: AsyncSession = Depends(get_db)) -> SweepOut:
    """Queue a run and return immediately — these take minutes to hours."""
    if sweeps.is_running():
        # One at a time on purpose: concurrent sweeps multiply the request
        # rate against Steam, which is the failure this project already hit.
        raise HTTPException(
            status_code=409,
            detail="A sweep is already running. Wait for it, or cancel it first.",
        )
    if (
        body.release_from is not None
        and body.release_to is not None
        and body.release_from > body.release_to
    ):
        raise HTTPException(status_code=422, detail="release_from is after release_to")

    job = SweepJob(
        kinds=body.kinds,
        release_from=body.release_from,
        release_to=body.release_to,
        limit_per_kind=body.limit_per_kind or None,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    sweeps.launch(job.id)
    return _out(job)


@router.get("/sweeps", response_model=list[SweepOut])
async def list_sweeps(db: AsyncSession = Depends(get_db)) -> list[SweepOut]:
    rows = (
        await db.execute(
            sa.select(SweepJob).order_by(SweepJob.created_at.desc()).limit(MAX_LISTED)
        )
    ).scalars().all()
    return [_out(job) for job in rows]


@router.post("/sweeps/{job_id}/cancel", response_model=SweepOut)
async def cancel_sweep(job_id: int, db: AsyncSession = Depends(get_db)) -> SweepOut:
    """Requests a stop. The runner checks between games, so a sweep ends
    within one request interval rather than immediately — and whatever it has
    already collected is committed."""
    job = await db.get(SweepJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Sweep not found")
    if job.status in ("done", "failed", "cancelled", "interrupted"):
        return _out(job)
    job.cancel_requested = True
    await db.commit()
    await db.refresh(job)
    return _out(job)
