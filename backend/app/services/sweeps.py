"""Execute admin-triggered collector runs and record their progress.

Runs in-process on the backend's event loop. That is appropriate here: every
collector is IO-bound and spends most of its time sleeping between polite
requests, so it does not compete with request handling — and this is a
single-operator research tool, not a multi-tenant service.

What it deliberately does NOT do is shell out to `docker compose run`, which
would need the Docker socket inside the container and would leave orphaned
containers behind when the client goes away (a failure this project has
already hit once).

A backend restart kills any in-flight run. That is recorded rather than
hidden: migration 0013 marks surviving rows `interrupted` on startup, and
every collector is resumable, so re-running continues where it stopped.
"""

import asyncio
import datetime
import logging

import sqlalchemy as sa

from app.db.session import async_session_factory
from app.models import SweepJob

logger = logging.getLogger(__name__)

# Only one sweep at a time. Concurrent runs would multiply the request rate
# against Steam — exactly what happened when orphaned containers overlapped.
_run_lock = asyncio.Lock()
_current_task: asyncio.Task | None = None


def is_running() -> bool:
    return _current_task is not None and not _current_task.done()


async def _set(job_id: int, **values) -> None:
    async with async_session_factory() as db:
        await db.execute(sa.update(SweepJob).where(SweepJob.id == job_id).values(**values))
        await db.commit()


async def _merge_progress(job_id: int, kind: str, payload: dict) -> None:
    async with async_session_factory() as db:
        job = await db.get(SweepJob, job_id)
        if job is None:
            return
        progress = dict(job.progress or {})
        progress[kind] = payload
        job.progress = progress
        await db.commit()


async def _cancel_requested(job_id: int) -> bool:
    async with async_session_factory() as db:
        return bool(
            await db.scalar(
                sa.select(SweepJob.cancel_requested).where(SweepJob.id == job_id)
            )
        )


async def _run_kind(job: SweepJob, kind: str) -> dict:
    """Dispatch one collector. Imported lazily so the API starts even if the
    scraper packages are missing from an older image."""
    on_progress = lambda payload: _merge_progress(job.id, kind, payload)  # noqa: E731
    should_stop = lambda: _cancel_requested(job.id)  # noqa: E731

    if kind == "followers":
        from workers.refresh_followers import run as run_followers

        return await run_followers(
            limit=job.limit_per_kind or 0,
            min_age_hours=20,
            include_released=job.release_from is not None or job.release_to is not None,
            dry_run=False,
            interval=4.0,
            release_from=job.release_from,
            release_to=job.release_to,
            on_progress=on_progress,
            should_stop=should_stop,
        )

    if kind == "disclosures":
        from workers.harvest_disclosures import run as run_disclosures

        return await run_disclosures(
            limit=job.limit_per_kind or 0,
            start_appid=0,
            only_appid=None,
            write=True,
            release_from=job.release_from,
            release_to=job.release_to,
            on_progress=on_progress,
            should_stop=should_stop,
        )

    if kind == "rank":
        # The chart is a single global list Valve orders itself, so a release
        # window does not apply. ~53 requests, a few minutes.
        from scraper.collectors.wishlist_rank import run_rank_sweep

        return await run_rank_sweep(dry_run=False)

    raise ValueError(f"unknown sweep kind: {kind}")


async def _execute(job_id: int) -> None:
    async with _run_lock:
        async with async_session_factory() as db:
            job = await db.get(SweepJob, job_id)
            if job is None:
                return
            kinds = list(job.kinds)
            # Detach a plain snapshot: the session closes below, and the
            # collectors open their own sessions.
            snapshot = SweepJob(
                id=job.id, kinds=kinds, release_from=job.release_from,
                release_to=job.release_to, limit_per_kind=job.limit_per_kind,
            )
        await _set(job_id, status="running", started_at=datetime.datetime.now(datetime.timezone.utc))

        results: dict = {}
        try:
            for kind in kinds:
                if await _cancel_requested(job_id):
                    break
                logger.info("sweep %s: starting %s", job_id, kind)
                summary = await _run_kind(snapshot, kind)
                results[kind] = summary
                await _merge_progress(job_id, kind, {**summary, "done": True})
        except Exception as exc:  # noqa: BLE001 — surface it on the job row
            logger.exception("sweep %s failed", job_id)
            await _set(
                job_id, status="failed", error=f"{exc.__class__.__name__}: {exc}"[:2000],
                finished_at=datetime.datetime.now(datetime.timezone.utc),
            )
            return

        cancelled = await _cancel_requested(job_id)
        await _set(
            job_id,
            status="cancelled" if cancelled else "done",
            finished_at=datetime.datetime.now(datetime.timezone.utc),
        )
        logger.info("sweep %s finished: %s", job_id, results)


def launch(job_id: int) -> None:
    """Fire-and-forget. A reference is kept so the task is not garbage
    collected mid-run, which asyncio does not otherwise guarantee."""
    global _current_task
    _current_task = asyncio.create_task(_execute(job_id))
