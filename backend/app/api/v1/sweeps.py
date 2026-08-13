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
from app.models import SWEEP_KINDS, TERMINAL_STATUSES, SweepJob
from app.services import sweep_eta, sweeps

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
    paused: bool = False
    created_at: datetime.datetime
    started_at: datetime.datetime | None = None
    finished_at: datetime.datetime | None = None
    # Last sign of life from the executing process. A CLI-driven sweep runs
    # outside this API, so a stale heartbeat is the only way to tell that its
    # shell loop was killed.
    heartbeat_at: datetime.datetime | None = None
    active_kind: str | None = None
    # "api" (run inside the backend) or "cli" (run by a sweep script).
    runner: str | None = None
    # Where a disclosures walk begins. Set when this run continues an earlier
    # one; null for a run that starts from the top.
    start_appid: int | None = None
    progress: dict = {}
    error: str | None = None
    # Work left and how long it should take. `eta_basis` says whether the
    # rate was measured from real throughput or assumed from the configured
    # request interval — the UI should not imply precision it does not have.
    remaining: int | None = None
    # Everything this sweep could visit. With `remaining` it gives job-level
    # progress — which for a CLI sweep is the only honest one, since its
    # counters describe the 400-game batch in flight.
    scope_total: int | None = None
    eta_seconds: int | None = None
    eta_basis: str | None = None


def _out(job: SweepJob, eta: dict | None = None) -> SweepOut:
    eta = eta or {}
    return SweepOut(
        id=job.id, kinds=list(job.kinds), release_from=job.release_from,
        release_to=job.release_to, limit_per_kind=job.limit_per_kind,
        status=job.status, cancel_requested=job.cancel_requested,
        paused=job.paused, created_at=job.created_at, started_at=job.started_at,
        finished_at=job.finished_at, heartbeat_at=job.heartbeat_at,
        active_kind=job.active_kind, runner=job.runner,
        start_appid=job.start_appid,
        progress=job.progress or {}, error=job.error,
        remaining=eta.get("remaining"), scope_total=eta.get("scope_total"),
        eta_seconds=eta.get("eta_seconds"),
        eta_basis=eta.get("basis"),
    )


async def _refuse_if_kind_is_live(db: AsyncSession, kinds: list[str]) -> None:
    """One sweep per collector, not one sweep overall.

    Each collector talks to a different Steam host, so followers and
    disclosures running together does not raise the request rate against
    either. Two of the SAME kind does, and that is the failure this project
    already hit when orphaned containers overlapped.

    Checked against the sweep_jobs table rather than the in-process runner: a
    CLI sweep hits Steam exactly as hard and runs in another process
    altogether, so the table is the only thing the two paths share.
    """
    rows = (
        await db.execute(
            sa.select(SweepJob.id, SweepJob.kinds).where(
                SweepJob.status.in_(("queued", "running", "paused"))
            )
        )
    ).all()
    wanted = set(kinds)
    for job_id, live_kinds in rows:
        clash = wanted & set(live_kinds)
        if clash:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Sweep {job_id} is already running {', '.join(sorted(clash))}. "
                    "Wait for it, or stop it first."
                ),
            )
    in_process = sweeps.running_kinds() & wanted
    if in_process:
        raise HTTPException(
            status_code=409,
            detail=f"{', '.join(sorted(in_process))} is already running here.",
        )


@router.post("/sweeps", response_model=SweepOut, status_code=202)
async def start_sweep(body: SweepRequest, db: AsyncSession = Depends(get_db)) -> SweepOut:
    """Queue a run and return immediately — these take minutes to hours."""
    await _refuse_if_kind_is_live(db, body.kinds)
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
        # Owned by this process, so a restart is known to have killed it.
        runner="api",
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
    out = []
    for job in rows:
        # Only compute for a live job: a finished one has no work left, and
        # the estimate costs a couple of aggregate queries.
        eta = (
            await sweep_eta.estimate(db, job)
            if job.status in ("queued", "running", "paused")
            else None
        )
        out.append(_out(job, eta))
    return out


@router.post("/sweeps/{job_id}/rerun", response_model=SweepOut, status_code=202)
async def rerun_sweep(job_id: int, db: AsyncSession = Depends(get_db)) -> SweepOut:
    """Continue a run that stopped early, as a new job.

    A new row rather than a revival of the old one: the original is a record of
    what happened, and overwriting its timing and counters would erase that.

    Every collector is resumable, but not in the same way. Followers and rank
    work out where to start from the database; disclosures cannot — it leaves
    no trace for the 95% of games that announced nothing — so its walk position
    is carried across explicitly.
    """
    source = await db.get(SweepJob, job_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Sweep not found")
    if source.status not in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Sweep {job_id} is {source.status} — stop it before re-running.",
        )
    await _refuse_if_kind_is_live(db, list(source.kinds))

    job = SweepJob(
        kinds=list(source.kinds),
        release_from=source.release_from,
        release_to=source.release_to,
        limit_per_kind=source.limit_per_kind,
        start_appid=await sweeps.resume_anchor(db, source),
        runner="api",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    sweeps.launch(job.id)
    return _out(job)


@router.post("/sweeps/{job_id}/pause", response_model=SweepOut)
async def pause_sweep(job_id: int, db: AsyncSession = Depends(get_db)) -> SweepOut:
    """Hold position. The worker checks between games, so it parks within one
    request interval and keeps everything already collected."""
    return await _set_flag(job_id, db, paused=True)


@router.post("/sweeps/{job_id}/resume", response_model=SweepOut)
async def resume_sweep(job_id: int, db: AsyncSession = Depends(get_db)) -> SweepOut:
    return await _set_flag(job_id, db, paused=False)


async def _set_flag(job_id: int, db: AsyncSession, *, paused: bool) -> SweepOut:
    job = await db.get(SweepJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Sweep not found")
    if job.status in ("done", "failed", "cancelled", "interrupted"):
        raise HTTPException(status_code=409, detail=f"Sweep is already {job.status}")
    job.paused = paused
    await db.commit()
    await db.refresh(job)
    return _out(job)


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
