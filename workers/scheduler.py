"""Run collectors on a cadence, so the deltas have something to difference.

Every movement signal in this project needs the same thing: the same
measurement taken twice, far enough apart. `rank_delta_7d` differences the
newest complete Top-Wishlists sweep against the newest one at least seven days
old, and `follower_delta_14d` does the same at fourteen. Until this existed
nothing ran a second sweep, so those two columns were structurally empty — not
"no movement", but "no second observation".

The rank sweep is the one worth scheduling tightly: 53 requests and about three
minutes for a chart of ~5,200 games, so a daily run costs almost nothing and
brings the 7-day delta online a week after the first run.

Followers are deliberately NOT scheduled here. A full catalogue pass is 23,078
games at 4s, which is ~26 hours — a daily cycle is not physically available, so
the follower series is built by leaving scripts/sweep-followers.sh running
rather than by a scheduler firing on a clock.

Each run registers a sweep_jobs row through job_control, so a scheduled sweep
appears in /admin/sweeps with progress and can be paused or stopped there like
any other.
"""

import asyncio
import datetime
import logging
import os

import sqlalchemy as sa
from app.db.session import async_session_factory
from app.models import SweepJob

from scraper.common.job_control import create_job, finish, make_controls, report

logger = logging.getLogger("scheduler")

# kind -> hours between runs. Only collectors whose cost justifies a clock.
DEFAULT_SCHEDULE = {"rank": 24.0}
# How often to wake and re-check. Short enough that a missed window is not
# missed by long, long enough that an idle scheduler costs nothing.
POLL_SECONDS = 300.0
LIVE_STATUSES = ("queued", "running", "paused")


def parse_schedule(raw: str | None) -> dict[str, float]:
    """"rank:24,disclosures:168" -> {"rank": 24.0, "disclosures": 168.0}.

    An empty string disables the scheduler entirely, which is the honest way
    to turn it off — better than commenting out a compose service and later
    wondering why the deltas stopped filling in.
    """
    if raw is None:
        return dict(DEFAULT_SCHEDULE)
    if not raw.strip():
        return {}
    schedule = {}
    for part in raw.split(","):
        kind, _, hours = part.partition(":")
        kind = kind.strip()
        if not kind:
            continue
        schedule[kind] = float(hours) if hours.strip() else 24.0
    return schedule


async def _last_finished(kind: str) -> datetime.datetime | None:
    """When a sweep of this kind last completed successfully.

    Only `done` counts. A cancelled or interrupted run left the chart half
    swept, and treating it as this cycle's run would skip a real one.
    """
    async with async_session_factory() as db:
        return await db.scalar(
            sa.select(sa.func.max(SweepJob.finished_at)).where(
                SweepJob.kinds.any(kind), SweepJob.status == "done"
            )
        )


async def _is_live(kind: str) -> bool:
    async with async_session_factory() as db:
        found = await db.scalar(
            sa.select(SweepJob.id)
            .where(SweepJob.kinds.any(kind), SweepJob.status.in_(LIVE_STATUSES))
            .limit(1)
        )
    return found is not None


async def _run(kind: str) -> None:
    """Execute one collector under its own job row."""
    job_id = await create_job([kind])
    logger.info("scheduled %s sweep started as job %s", kind, job_id)
    try:
        if kind == "rank":
            from scraper.collectors.wishlist_rank import run_rank_sweep

            summary = await run_rank_sweep(dry_run=False)
        elif kind == "disclosures":
            # The catalogue walk finishes; what a repeat pass picks up is new
            # announcements since the last one. Weekly is the sensible cadence
            # — a full pass is ~9.6h, and developers do not post milestones
            # daily. --write is implied: a scheduled dry run would produce a
            # CSV nobody reads.
            from workers.harvest_disclosures import run as run_disclosures

            on_progress, should_stop = make_controls(job_id, kind)
            summary = await run_disclosures(
                limit=0,
                start_appid=0,
                only_appid=None,
                write=True,
                on_progress=on_progress,
                should_stop=should_stop,
            )
        else:
            raise ValueError(f"scheduler cannot run kind '{kind}'")
    except Exception as exc:  # one bad run must not end the loop
        logger.exception("scheduled %s sweep failed", kind)
        await finish(job_id, "failed", f"{exc.__class__.__name__}: {exc}"[:2000])
        return
    # Report the counters too, so a scheduled run shows the same detail in
    # /admin/sweeps as a hand-started one rather than an empty card.
    if isinstance(summary, dict):
        await report(job_id, kind, {**summary, "done": True})
    await finish(job_id, "done")
    logger.info("scheduled %s sweep finished: %s", kind, summary)


async def due(kind: str, every_hours: float) -> bool:
    """Whether `kind` should run now."""
    if await _is_live(kind):
        # Somebody is already running it — a hand-started sweep, or the last
        # scheduled one still going. Firing a second would double the request
        # rate against the same Steam host.
        logger.debug("%s already running, skipping", kind)
        return False
    last = await _last_finished(kind)
    if last is None:
        return True
    age_hours = (datetime.datetime.now(datetime.timezone.utc) - last).total_seconds() / 3600
    return age_hours >= every_hours


async def tick(schedule: dict[str, float]) -> None:
    for kind, every_hours in schedule.items():
        if await due(kind, every_hours):
            await _run(kind)


async def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    schedule = parse_schedule(os.environ.get("SWEEP_SCHEDULE"))
    if not schedule:
        logger.info("SWEEP_SCHEDULE is empty — nothing to run, idling.")
    else:
        logger.info(
            "scheduling %s",
            ", ".join(f"{kind} every {hours}h" for kind, hours in schedule.items()),
        )
    while True:
        try:
            await tick(schedule)
        except Exception:  # the loop outlives any single failure
            logger.exception("scheduler tick failed")
        await asyncio.sleep(POLL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
