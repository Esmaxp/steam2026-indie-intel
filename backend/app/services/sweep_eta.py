"""How much work is left in a sweep, and how long it should take.

Two numbers: games remaining, and seconds per game.

Games remaining is counted in the DATABASE, with the same predicate the
collector selects on. Not from a job's progress counters — a CLI-driven sweep
runs as a series of independent batches, so its `total`/`processed` describe
the batch in flight, and an ETA built from them would report minutes on a job
with hours to go.

Seconds per game is reported by the process doing the work, which is the only
thing that knows how long a game actually took. An earlier version inferred it
from the rows the follower collector wrote, which meant dividing by the share
of games that have a community hub — a small, noisy sample early in a run.
That divisor swung the estimate between 13h and 26h on a sweep whose real pace
never moved off 3.97s per game. The worker's own elapsed/processed has no such
term, and covers the disclosure harvester too, which leaves no per-game trail
to infer anything from.

Where a run has not yet timed enough games, the collector's configured request
interval is used instead. Which of the two produced the number is returned
alongside it, so the UI can say "measured" or "assumed" rather than implying
more precision than exists.
"""

import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FollowerSnapshot, Game

# Configured request spacing per collector (seconds), matching the workers.
# Checked against real runs: followers 3.97s observed against 4.0 configured,
# disclosures 1.48-1.54s against 1.5. The interval is a floor the collector
# enforces, so it dominates everything else in the loop.
NOMINAL_INTERVAL = {"followers": 4.0, "disclosures": 1.5, "rank": 3.0}
# Games a run must have timed before its own pace beats the configured one.
# At 4s a game that is ~100 seconds in.
MIN_TIMING_SAMPLES = 25
# Matches refresh_followers' default staleness cutoff.
FOLLOWER_MIN_AGE_HOURS = 20
UNKNOWN = {
    "remaining": None,
    "scope_total": None,
    "eta_seconds": None,
    "basis": "unknown",
}


def seconds_per_game(progress: dict) -> float | None:
    """The run's own measured pace, or None if it has not timed enough games.

    `elapsed` excludes time parked at a pause, so a resumed run is not
    reported as permanently slower than it is.
    """
    processed = int(progress.get("processed") or 0)
    elapsed = float(progress.get("elapsed") or 0)
    if processed < MIN_TIMING_SAMPLES or elapsed <= 0:
        return None
    return elapsed / processed


def _latest_follower_sq():
    return (
        sa.select(FollowerSnapshot.appid, FollowerSnapshot.captured_at)
        .distinct(FollowerSnapshot.appid)
        .order_by(FollowerSnapshot.appid, FollowerSnapshot.captured_at.desc())
        .subquery("latest_follower")
    )


def _scope(
    include_released: bool,
    release_from: datetime.date | None,
    release_to: datetime.date | None,
):
    """Every game this sweep could visit, before subtracting what is done."""
    stmt = sa.select(sa.func.count()).select_from(Game)
    if not include_released:
        stmt = stmt.where(Game.is_released.is_(False))
    if release_from is not None:
        stmt = stmt.where(Game.release_date >= release_from)
    if release_to is not None:
        stmt = stmt.where(Game.release_date <= release_to)
    return stmt


async def _remaining_followers(
    db: AsyncSession,
    include_released: bool,
    release_from: datetime.date | None,
    release_to: datetime.date | None,
) -> tuple[int, int]:
    """(remaining, scope_total).

    Remaining mirrors refresh_followers.select_stale(): no snapshot, or one
    older than the staleness cutoff.
    """
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        hours=FOLLOWER_MIN_AGE_HOURS
    )
    lf = _latest_follower_sq()
    stmt = (
        _scope(include_released, release_from, release_to)
        .outerjoin(lf, lf.c.appid == Game.appid)
        .where(sa.or_(lf.c.appid.is_(None), lf.c.captured_at < cutoff))
    )
    total = (
        await db.execute(_scope(include_released, release_from, release_to))
    ).scalar_one()
    return (await db.execute(stmt)).scalar_one(), total


async def _remaining_disclosures(
    db: AsyncSession,
    appid: int | None,
    release_from: datetime.date | None,
    release_to: datetime.date | None,
) -> tuple[int, int]:
    """(remaining, scope_total) for the appid-ordered walk.

    The harvester writes only for the ~5% of games that announced anything,
    so unlike followers there is no per-game trail in the database — the walk
    position reported by the worker is the only anchor.
    """
    left = _scope(True, release_from, release_to)
    if appid is not None:
        left = left.where(Game.appid > appid)
    total = (await db.execute(_scope(True, release_from, release_to))).scalar_one()
    return (await db.execute(left)).scalar_one(), total


async def estimate(db: AsyncSession, job, kind: str | None = None) -> dict:
    """-> {remaining, scope_total, eta_seconds, basis} for the running kind."""
    kind = kind or job.active_kind or (job.kinds[0] if job.kinds else None)
    if kind is None:
        return dict(UNKNOWN)
    progress = (job.progress or {}).get(kind) or {}

    if kind == "rank":
        # One bounded sweep of a chart Valve paginates itself: ~53 requests,
        # a few minutes. Not worth counting rows for.
        return {
            "remaining": None,
            "scope_total": None,
            "eta_seconds": 200,
            "basis": "estimated",
        }

    if kind == "followers":
        # The worker reports its own scope, because a job row cannot express
        # "upcoming only" — the API path infers that from the release window
        # and the CLI path takes it as a flag. Absent a report, assume the
        # broader scope so the ETA is not optimistic.
        include_released = bool(progress.get("include_released", True))
        remaining, scope_total = await _remaining_followers(
            db, include_released, job.release_from, job.release_to
        )
    elif kind == "disclosures":
        # The walk position once the run reports one; until then, where the
        # row says it began. Without the fallback a continuation claims the
        # whole catalogue is left for its first minute.
        appid = progress.get("appid") or job.start_appid
        remaining, scope_total = await _remaining_disclosures(
            db, int(appid) if appid else None, job.release_from, job.release_to
        )
    else:
        return dict(UNKNOWN)

    # A paused run has no progress to measure right now, but the pace it was
    # last making is still the right answer for "how long once resumed".
    pace = seconds_per_game(progress)
    return {
        "remaining": remaining,
        "scope_total": scope_total,
        "eta_seconds": int(remaining * (pace or NOMINAL_INTERVAL[kind])),
        "basis": "measured" if pace else "estimated",
    }
