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
hidden: migration 0014 marks surviving rows `interrupted` on startup, and
every collector is resumable, so re-running continues where it stopped.

Progress reporting and the pause/stop checks are NOT implemented here — they
come from scraper.common.job_control, which the CLI sweep scripts use too. One
implementation means the admin UI's buttons work identically whichever way a
sweep was started.
"""

import asyncio
import contextlib
import datetime
import logging

import sqlalchemy as sa

from app.db.session import async_session_factory
from app.models import Game, SweepJob

logger = logging.getLogger(__name__)

# One sweep per collector, not one sweep overall. Each collector talks to a
# different Steam host — followers to steamcommunity.com, disclosures to
# api.steampowered.com, rank to store.steampowered.com — so running two
# different ones concurrently does not raise the request rate against any of
# them. Two of the SAME kind does, which is the failure this project already
# hit when orphaned containers overlapped.
_kind_locks: dict[str, asyncio.Lock] = {}
# Strong references, so a run is not garbage collected mid-flight — asyncio
# does not otherwise guarantee it.
_tasks: set[asyncio.Task] = set()


def _lock_for(kind: str) -> asyncio.Lock:
    return _kind_locks.setdefault(kind, asyncio.Lock())


def running_kinds() -> set[str]:
    """Collectors busy in THIS process. Says nothing about CLI sweeps, which
    run elsewhere — the database is what those two paths share."""
    return {kind for kind, lock in _kind_locks.items() if lock.locked()}


async def _set(job_id: int, **values) -> None:
    async with async_session_factory() as db:
        await db.execute(sa.update(SweepJob).where(SweepJob.id == job_id).values(**values))
        await db.commit()


def walk_position(progress: dict, runner: str | None) -> tuple[str, int] | None:
    """How far a disclosures run got: ("appid", n) or ("scanned", n).

    Runs since the walk position was recorded report the appid directly. Older
    rows recorded only how many games they scanned, which still locates the
    position because the walk is appid-ordered — but only for a run that
    scanned in one pass. A CLI run reports `processed` per batch, so its count
    means nothing globally and is refused rather than guessed at.
    """
    appid = progress.get("appid")
    if appid:
        return ("appid", int(appid))
    if runner == "cli":
        return None
    processed = int(progress.get("processed") or 0)
    return ("scanned", processed) if processed > 0 else None


async def resume_anchor(db, job: SweepJob) -> int | None:
    """Where a re-run of `job` should pick up. None = start from the top.

    Only disclosures needs one. The follower collector resumes for free —
    select_stale() skips anything already fresh — and the rank sweep is a few
    minutes end to end.
    """
    if "disclosures" not in job.kinds:
        return None
    position = walk_position((job.progress or {}).get("disclosures") or {}, job.runner)
    if position is None:
        return None
    basis, value = position
    if basis == "appid":
        return value + 1  # resume past the last game it read

    # A count rather than an appid: find the game that many places into the
    # walk, counting from wherever that run itself began.
    scanned = value
    start = job.start_appid or 0
    last = await db.scalar(
        sa.select(Game.appid)
        .where(Game.appid >= start)
        .order_by(Game.appid)
        .offset(scanned - 1)
        .limit(1)
    )
    return (last + 1) if last is not None else None


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
    from scraper.common.job_control import make_controls

    on_progress, should_stop = make_controls(job.id, kind)

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
            start_appid=job.start_appid or 0,
            only_appid=None,
            write=True,
            release_from=job.release_from,
            release_to=job.release_to,
            on_progress=on_progress,
            should_stop=should_stop,
        )

    if kind == "rank":
        # The chart is a single global list Valve orders itself, so a release
        # window does not apply. ~53 requests, a few minutes. It takes no
        # control hooks — at a few minutes long, pausing it has no value.
        from scraper.collectors.wishlist_rank import run_rank_sweep

        return await run_rank_sweep(dry_run=False)

    raise ValueError(f"unknown sweep kind: {kind}")


async def _execute(job_id: int) -> None:
    async with async_session_factory() as db:
        row = await db.get(SweepJob, job_id)
        if row is None:
            return
        kinds_for_lock = sorted(row.kinds)
    # Sorted so two jobs requesting overlapping kinds cannot deadlock by
    # taking them in opposite orders.
    async with contextlib.AsyncExitStack() as stack:
        for kind in kinds_for_lock:
            await stack.enter_async_context(_lock_for(kind))
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
                start_appid=job.start_appid,
            )
        await _set(job_id, status="running", started_at=datetime.datetime.now(datetime.timezone.utc))

        from scraper.common.job_control import report

        results: dict = {}
        try:
            for kind in kinds:
                if await _cancel_requested(job_id):
                    break
                logger.info("sweep %s: starting %s", job_id, kind)
                await _set(job_id, active_kind=kind)
                summary = await _run_kind(snapshot, kind)
                results[kind] = summary
                # Not "done" if it was stopped part-way: the badge would
                # claim a cancelled run finished its work.
                await report(
                    job_id, kind, {**summary, "done": not summary.get("stopped")}
                )
        except Exception as exc:  # noqa: BLE001 — surface it on the job row
            logger.exception("sweep %s failed", job_id)
            await _set(
                job_id, status="failed", error=f"{exc.__class__.__name__}: {exc}"[:2000],
                paused=False, paused_at=None, active_kind=None,
                finished_at=datetime.datetime.now(datetime.timezone.utc),
            )
            return

        cancelled = await _cancel_requested(job_id)
        await _set(
            job_id,
            status="cancelled" if cancelled else "done",
            # Clear the hold, so a paused-then-cancelled job does not come back
            # looking pausable in the UI.
            paused=False,
            paused_at=None,
            active_kind=None,
            finished_at=datetime.datetime.now(datetime.timezone.utc),
        )
        logger.info("sweep %s finished: %s", job_id, results)


def launch(job_id: int) -> None:
    """Fire-and-forget, with a reference held until the run ends."""
    task = asyncio.create_task(_execute(job_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
