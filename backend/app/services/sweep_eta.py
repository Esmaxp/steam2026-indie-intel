"""How much work is left in a sweep, and how long it should take.

Deliberately derived from the DATABASE rather than from a job's progress
counters. A CLI-driven sweep runs as a series of independent batches, so its
`total`/`processed` describe the current batch only — an ETA built from them
would report minutes remaining on a job with hours to go.

Remaining work is counted with the same predicate the collector selects on, so
the number is what the worker will actually visit, not a proxy for it.

Rate is measured where the collector leaves a timestamped trail, and falls
back to the configured request interval where it does not. Which of the two
produced a number is returned alongside it, so the UI can say "measured" or
"estimated" instead of implying more precision than exists.
"""

import datetime
import itertools
import statistics

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FollowerSnapshot, Game

# Configured request spacing per collector (seconds), matching the workers.
NOMINAL_INTERVAL = {"followers": 4.0, "disclosures": 1.5, "rank": 3.0}
# Window for measuring real throughput. Wide enough to hold several commit
# batches — the estimator needs a few to take a median of — but still recent
# enough to describe the rate now.
RATE_WINDOW_MINUTES = 25
# Fewer gaps than this and a median is not a median.
MIN_RATE_BATCHES = 4
# Games a run must have visited before its hub-hit ratio means anything. The
# ratio divides the rate, so sampling noise lands in the ETA amplified: 44/50
# instead of the true ~0.95 is enough to shave an hour off an 18h estimate.
# ~7 minutes into a follower sweep, which is exactly the period where the
# nominal interval is a perfectly good answer anyway.
MIN_HIT_RATIO_SAMPLES = 100
# Matches refresh_followers' default staleness cutoff.
FOLLOWER_MIN_AGE_HOURS = 20
UNKNOWN = {"remaining": None, "eta_seconds": None, "basis": "unknown"}


def _latest_follower_sq():
    return (
        sa.select(FollowerSnapshot.appid, FollowerSnapshot.captured_at)
        .distinct(FollowerSnapshot.appid)
        .order_by(FollowerSnapshot.appid, FollowerSnapshot.captured_at.desc())
        .subquery("latest_follower")
    )


async def _remaining_followers(
    db: AsyncSession,
    include_released: bool,
    release_from: datetime.date | None,
    release_to: datetime.date | None,
) -> int:
    """Mirrors refresh_followers.select_stale(): no snapshot, or a stale one."""
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        hours=FOLLOWER_MIN_AGE_HOURS
    )
    lf = _latest_follower_sq()
    stmt = (
        sa.select(sa.func.count())
        .select_from(Game)
        .outerjoin(lf, lf.c.appid == Game.appid)
        .where(sa.or_(lf.c.appid.is_(None), lf.c.captured_at < cutoff))
    )
    if not include_released:
        stmt = stmt.where(Game.is_released.is_(False))
    if release_from is not None:
        stmt = stmt.where(Game.release_date >= release_from)
    if release_to is not None:
        stmt = stmt.where(Game.release_date <= release_to)
    return (await db.execute(stmt)).scalar_one()


def rate_from_batches(batches: list[tuple[datetime.datetime, int]]) -> float | None:
    """Rows per second, from the median of per-batch rates.

    The worker commits every 50 rows, so `captured_at` clusters: fifty rows
    share one timestamp, and the trail is a handful of spikes rather than a
    smooth series. Two consequences drive the shape of this function.

    Each batch's rows are charged to the gap BEFORE it — that is the interval
    that produced them. Dividing the row count by the span from first to last
    timestamp instead would ignore the minutes that produced the first batch
    and read about twice the true rate.

    The median across batches, not the mean, because a paused sweep leaves one
    enormous gap in the window. A mean would let that one idle stretch drag the
    estimate down by any factor at all — a twenty-minute pause inside a
    twenty-five-minute window would report a rate ten times too slow, and an
    ETA of days. A median simply discards it as the outlier it is.
    """
    if len(batches) < MIN_RATE_BATCHES:
        return None
    rates = []
    for (prev_at, _), (at, rows) in itertools.pairwise(batches):
        gap = (at - prev_at).total_seconds()
        if gap > 0:
            rates.append(rows / gap)
    if len(rates) < MIN_RATE_BATCHES - 1:
        return None
    return statistics.median(rates)


async def _observed_follower_rate(
    db: AsyncSession, hit_ratio: float | None
) -> float | None:
    """Games visited per second, measured, or None if there is too little to
    measure from.

    Divided by the hit ratio because a game with no community hub writes
    nothing: snapshots-per-second is a visit rate only for the games that have
    a hub. Without that ratio there is no honest conversion, so no measurement.
    """
    if not hit_ratio or hit_ratio <= 0:
        return None
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        minutes=RATE_WINDOW_MINUTES
    )
    batches = [
        (row[0], row[1])
        for row in (
            await db.execute(
                sa.select(FollowerSnapshot.captured_at, sa.func.count())
                .where(FollowerSnapshot.captured_at >= cutoff)
                .group_by(FollowerSnapshot.captured_at)
                .order_by(FollowerSnapshot.captured_at)
            )
        ).all()
    ]
    rate = rate_from_batches(batches)
    return None if rate is None else rate / hit_ratio


def _hit_ratio(progress: dict) -> float | None:
    """Fraction of visited games that produced a snapshot, from this run's own
    counters — or None when the run has not said yet.

    Deliberately not a guessed constant. The ratio is what converts a write
    rate into a visit rate, and it varies with the slice of the catalogue
    being swept; a wrong assumption lands directly in the ETA. An early
    version assumed 0.75 against a real ratio of ~0.97 and reported 13.5h on
    an 18h sweep. Better to quote the nominal interval for the first minute or
    two and switch to a measured rate once the run has evidence.
    """
    processed = int(progress.get("processed") or 0)
    written = int(progress.get("written") or 0)
    if processed < MIN_HIT_RATIO_SAMPLES or written == 0:
        return None
    return written / processed


async def _remaining_disclosures(
    db: AsyncSession,
    appid: int | None,
    release_from: datetime.date | None,
    release_to: datetime.date | None,
) -> int:
    """Games left in the appid-ordered walk.

    The harvester writes only for the ~5% of games that announced anything,
    so unlike followers there is no per-game trail in the database — the walk
    position reported by the worker is the only anchor.
    """
    stmt = sa.select(sa.func.count()).select_from(Game)
    if appid is not None:
        stmt = stmt.where(Game.appid > appid)
    if release_from is not None:
        stmt = stmt.where(Game.release_date >= release_from)
    if release_to is not None:
        stmt = stmt.where(Game.release_date <= release_to)
    return (await db.execute(stmt)).scalar_one()


async def estimate(db: AsyncSession, job, kind: str | None = None) -> dict:
    """-> {remaining, eta_seconds, basis} for the collector `job` is running."""
    kind = kind or job.active_kind or (job.kinds[0] if job.kinds else None)
    if kind is None:
        return dict(UNKNOWN)
    progress = (job.progress or {}).get(kind) or {}

    if kind == "followers":
        # The worker reports its own scope, because a job row cannot express
        # "upcoming only" — the API path infers that from the release window
        # and the CLI path takes it as a flag. Absent a report, assume the
        # broader scope so the ETA is not optimistic.
        include_released = bool(progress.get("include_released", True))
        remaining = await _remaining_followers(
            db, include_released, job.release_from, job.release_to
        )
        # A paused sweep has no throughput to measure — whatever is left in
        # the window describes the minutes before it parked, and shrinks
        # misleadingly the longer it stays parked. Quote the nominal interval
        # instead: what it will take once resumed.
        rate = (
            None
            if job.status == "paused"
            else await _observed_follower_rate(db, _hit_ratio(progress))
        )
        if rate:
            return {
                "remaining": remaining,
                "eta_seconds": int(remaining / rate),
                "basis": "measured",
            }
        return {
            "remaining": remaining,
            "eta_seconds": int(remaining * NOMINAL_INTERVAL["followers"]),
            "basis": "estimated",
        }

    if kind == "disclosures":
        appid = progress.get("appid")
        remaining = await _remaining_disclosures(
            db, int(appid) if appid else None, job.release_from, job.release_to
        )
        return {
            "remaining": remaining,
            "eta_seconds": int(remaining * NOMINAL_INTERVAL["disclosures"]),
            "basis": "estimated",
        }

    if kind == "rank":
        # One bounded sweep of a chart Valve paginates itself: ~53 requests,
        # a few minutes. Not worth counting rows for.
        return {"remaining": None, "eta_seconds": 200, "basis": "estimated"}

    return dict(UNKNOWN)
