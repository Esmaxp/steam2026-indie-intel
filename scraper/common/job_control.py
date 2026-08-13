"""Bind a long-running collector to a sweep_jobs row.

A sweep can be driven two ways: the backend runs it in-process for the admin
UI, or a shell loop runs it batch by batch from the CLI. Both need the same
three things — report progress, honour pause, honour stop — so the contract
lives here once and each caller supplies only a job id.

The control flags are read from the database on every check rather than
cached, which is the point: the process doing the work and the process
serving the Pause button are different processes, and the row is the only
thing they share.
"""

import asyncio
import datetime
import logging

import sqlalchemy as sa
from app.db.session import async_session_factory
from app.models import SweepJob

logger = logging.getLogger(__name__)

# How long to sleep between re-reads while paused. Short enough that Resume
# feels immediate, long enough not to poll the database pointlessly.
PAUSE_POLL_SECONDS = 2.0


async def create_job(kinds: list[str], limit_per_kind: int | None = None) -> int:
    """Register a CLI-driven run so it appears in the admin UI."""
    async with async_session_factory() as db:
        job = SweepJob(
            kinds=kinds,
            limit_per_kind=limit_per_kind,
            status="running",
            # Owned by a separate process, so a backend restart must leave it
            # alone — it keeps running.
            runner="cli",
            started_at=datetime.datetime.now(datetime.timezone.utc),
            heartbeat_at=datetime.datetime.now(datetime.timezone.utc),
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def read_flags(job_id: int) -> tuple[bool, bool]:
    """(paused, cancel_requested). A missing row reads as cancelled, so
    deleting a job stops its worker rather than orphaning it."""
    async with async_session_factory() as db:
        row = (
            await db.execute(
                sa.select(SweepJob.paused, SweepJob.cancel_requested).where(
                    SweepJob.id == job_id
                )
            )
        ).first()
    if row is None:
        return False, True
    return bool(row[0]), bool(row[1])


async def report(job_id: int, kind: str, payload: dict) -> None:
    """Merge one collector's counters into the job and stamp the heartbeat.

    Merged into the kind's existing payload, not written over it. Live
    counters and the end-of-run summary do not carry the same keys, and a
    summary that replaced the counters would discard the walk position a
    disclosures run needs in order to be continued.
    """
    async with async_session_factory() as db:
        job = await db.get(SweepJob, job_id)
        if job is None:
            return
        progress = dict(job.progress or {})
        progress[kind] = {**(progress.get(kind) or {}), **payload}
        job.progress = progress
        job.active_kind = kind
        job.heartbeat_at = datetime.datetime.now(datetime.timezone.utc)
        await db.commit()


async def finish(job_id: int, status: str, error: str | None = None) -> None:
    async with async_session_factory() as db:
        job = await db.get(SweepJob, job_id)
        if job is None:
            return
        job.status = status
        job.error = error
        job.active_kind = None
        job.finished_at = datetime.datetime.now(datetime.timezone.utc)
        await db.commit()


def make_controls(job_id: int, kind: str):
    """-> (on_progress, should_stop) for the collector's existing hooks.

    Pause is folded into should_stop rather than exposed separately: the
    collector calls it between games, so blocking there IS the pause, and no
    collector needs to learn a third concept. It returns True only for a real
    stop.
    """

    async def on_progress(payload: dict) -> None:
        await report(job_id, kind, payload)

    async def should_stop() -> bool:
        paused, cancelled = await read_flags(job_id)
        if cancelled:
            return True
        if not paused:
            return False

        logger.info("job %s paused — holding position", job_id)
        async with async_session_factory() as db:
            job = await db.get(SweepJob, job_id)
            if job is not None and job.status == "running":
                job.status = "paused"
                await db.commit()

        while True:
            await asyncio.sleep(PAUSE_POLL_SECONDS)
            paused, cancelled = await read_flags(job_id)
            # Heartbeat while parked, so a paused job is still visibly alive.
            async with async_session_factory() as db:
                job = await db.get(SweepJob, job_id)
                if job is not None:
                    job.heartbeat_at = datetime.datetime.now(datetime.timezone.utc)
                    await db.commit()
            if cancelled:
                return True
            if not paused:
                logger.info("job %s resumed", job_id)
                async with async_session_factory() as db:
                    job = await db.get(SweepJob, job_id)
                    if job is not None and job.status == "paused":
                        job.status = "running"
                        await db.commit()
                return False

    return on_progress, should_stop


def _cli() -> None:
    """Let the shell sweep scripts register and close a job.

    The scripts drive a sweep as a series of short-lived containers, so there
    is no long-lived Python process to own the row — it has to be created
    before the first batch and closed after the last one.

        id=$(python -m scraper.common.job_control create followers)
        python -m scraper.common.job_control finish "$id" done
    """
    import sys

    args = sys.argv[1:]
    if args and args[0] == "create":
        kinds = args[1].split(",") if len(args) > 1 else []
        print(asyncio.run(create_job(kinds)))
        return
    if args and args[0] == "finish":
        asyncio.run(finish(int(args[1]), args[2] if len(args) > 2 else "done"))
        return
    if args and args[0] == "flags":
        paused, cancelled = asyncio.run(read_flags(int(args[1])))
        print(f"{int(paused)} {int(cancelled)}")
        return
    raise SystemExit("usage: job_control (create <kinds>|finish <id> [status]|flags <id>)")


if __name__ == "__main__":
    _cli()
