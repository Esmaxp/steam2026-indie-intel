"""Harvest developer-disclosed wishlist counts from official Steam news.

Writes CONFIRMED wishlist_records — the highest trust tier in this codebase,
and the only tier the wishlist column will ever display. Because
disclosed_numbers_source.py sets the bar for CONFIRMED at "a human read the
source and supplied the URL", an automated harvester must not silently lower
it: this defaults to --dry-run and requires an explicit --write.

Dry runs write a CSV to $LOGS_DIR for review, with the matched sentence for
every row so a human can check the extraction before promoting it.

Re-runs are safe: the partial unique index on
(appid, source_url, wishlist_count) makes ingestion idempotent.

Usage:
    python -m workers.harvest_disclosures --limit 200            # dry run
    python -m workers.harvest_disclosures --limit 200 --write
    python -m workers.harvest_disclosures --appid 4393700
    docker compose run --rm disclosures
"""

import argparse
import asyncio
import csv
import datetime
import os
from collections.abc import Awaitable, Callable

import sqlalchemy as sa

from app.db.session import async_session_factory
from app.models import DataStatus, Game, WishlistRecord
from scraper.collectors.market_sources import fetch_news_items
from scraper.collectors.wishlist_disclosures import Disclosure, find_wishlist_disclosures
from scraper.common.http import SteamClient, make_session
from scraper.common.logging import setup_logging

# The Steam news API is Valve's own and tolerant, but stay polite: this is
# the same interval market_data uses for the Steam host.
MIN_INTERVAL = 1.5
PROGRESS_EVERY = 50
SOURCE_PREFIX = "Developer announcement"


async def select_targets(
    limit: int,
    start_appid: int,
    only_appid: int | None,
    release_from: datetime.date | None = None,
    release_to: datetime.date | None = None,
) -> list[int]:
    """Upcoming and recently released games, appid order.

    Ordering by appid rather than a last-harvested timestamp keeps this
    resumable with --start-appid and needs no extra column: re-running is
    harmless anyway because ingestion is idempotent.

    A release_from/release_to window replaces the default "upcoming or
    released within a year" rule, so a caller can target one slice of the
    catalogue instead of all of it.
    """
    async with async_session_factory() as db:
        if only_appid is not None:
            return [only_appid]
        stmt = sa.select(Game.appid).where(Game.appid >= start_appid)
        if release_from is None and release_to is None:
            cutoff = datetime.date.today() - datetime.timedelta(days=365)
            stmt = stmt.where(
                sa.or_(Game.is_released.is_(False), Game.release_date >= cutoff)
            )
        else:
            if release_from is not None:
                stmt = stmt.where(Game.release_date >= release_from)
            if release_to is not None:
                stmt = stmt.where(Game.release_date <= release_to)
        stmt = stmt.order_by(Game.appid)
        if limit:
            stmt = stmt.limit(limit)
        return list((await db.execute(stmt)).scalars().all())


def write_csv(rows: list[Disclosure], logs_dir: str) -> str:
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = os.path.join(logs_dir, f"wishlist_disclosures_{stamp}.csv")
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["appid", "wishlists", "comparator", "disclosed_on", "title", "url", "excerpt"]
        )
        for row in rows:
            writer.writerow([
                row.appid, row.wishlists, row.comparator, row.disclosed_on.isoformat(),
                row.title, row.url, row.excerpt,
            ])
    return path


async def persist(rows: list[Disclosure]) -> int:
    """Insert as CONFIRMED. The partial unique index absorbs re-runs."""
    written = 0
    async with async_session_factory() as db:
        for row in rows:
            exists = (
                await db.execute(
                    sa.select(WishlistRecord.id).where(
                        WishlistRecord.appid == row.appid,
                        WishlistRecord.source_url == row.url,
                        WishlistRecord.wishlist_count == row.wishlists,
                    )
                )
            ).scalar_one_or_none()
            if exists is not None:
                continue
            db.add(
                WishlistRecord(
                    appid=row.appid,
                    status=DataStatus.CONFIRMED,
                    wishlist_count=row.wishlists,
                    comparator=row.comparator,
                    disclosed_on=row.disclosed_on,
                    source_name=f"{SOURCE_PREFIX}: {row.title}"[:300],
                    source_url=row.url,
                    notes="as reported by the developer",
                )
            )
            written += 1
        await db.commit()
    return written


async def run(
    limit: int,
    start_appid: int,
    only_appid: int | None,
    write: bool,
    release_from: datetime.date | None = None,
    release_to: datetime.date | None = None,
    on_progress: "Callable[[dict], Awaitable[None]] | None" = None,
    should_stop: "Callable[[], Awaitable[bool]] | None" = None,
) -> dict:
    """on_progress/should_stop let the admin sweep runner show live counters
    and stop a long run between games; both are optional so the CLI is
    unchanged."""
    logger = setup_logging("harvest_disclosures")
    appids = await select_targets(limit, start_appid, only_appid, release_from, release_to)
    logger.info(
        "Scanning news for %s games at %.1fs%s",
        len(appids), MIN_INTERVAL, "" if write else " [dry-run]",
    )

    found: list[Disclosure] = []
    failed = 0
    stopped = False
    # Walk position, so a run that ends early can be continued. Nothing else
    # records it: this collector writes rows only for the ~5% of games that
    # announced a figure, so the other 95% leave no trace of being read.
    last_appid = 0
    visited = 0
    async with make_session() as http:
        client = SteamClient(http, min_interval=MIN_INTERVAL)
        for index, appid in enumerate(appids, start=1):
            last_appid = appid
            visited = index
            try:
                items = await fetch_news_items(client, appid)
            except Exception as exc:  # noqa: BLE001 — one bad game must not end the run
                failed += 1
                logger.warning("news fetch failed for %s: %s", appid, exc)
                continue
            hits = find_wishlist_disclosures(appid, items)
            if hits:
                logger.info(
                    "appid %s: %s", appid,
                    ", ".join(f"{h.comparator}{h.wishlists} on {h.disclosed_on}" for h in hits),
                )
            found.extend(hits)
            if index % PROGRESS_EVERY == 0:
                logger.info(
                    "%s/%s scanned — %s disclosures so far", index, len(appids), len(found)
                )
                if on_progress is not None:
                    await on_progress({
                        "total": len(appids), "processed": index,
                        # The walk position in the catalogue. `processed`
                        # counts only within this batch, so a CLI-driven sweep
                        # needs the appid to know how far it has really got.
                        "appid": appid,
                        "found": len(found),
                        "games_with_disclosures": len({d.appid for d in found}),
                        "failed": failed,
                    })
            if should_stop is not None and await should_stop():
                logger.info("stop requested — ending after %s games", index)
                stopped = True
                break

    summary = {
        # Games SELECTED for this run. The sweep script compares it against
        # the batch size to detect the end of the catalogue, so it must stay
        # the selected count even when the run stops early.
        "scanned": len(appids),
        # Games actually read, and where the walk got to.
        "processed": visited,
        "appid": last_appid,
        "games_with_disclosures": len({d.appid for d in found}),
        "disclosures": len(found),
        "failed": failed,
        "stopped": stopped,
    }
    if write:
        summary["written"] = await persist(found)
    else:
        logs_dir = os.environ.get("LOGS_DIR", "logs")
        os.makedirs(logs_dir, exist_ok=True)
        summary["csv"] = write_csv(found, logs_dir)
        summary["written"] = 0
    logger.info("Summary: %s", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Harvest developer-disclosed wishlist counts from Steam news"
    )
    parser.add_argument("--limit", type=int, default=500, help="max games (0 = all)")
    parser.add_argument(
        "--start-appid", type=int, default=0, help="resume from this appid (appid order)"
    )
    parser.add_argument("--appid", type=int, default=None, help="scan a single game")
    parser.add_argument(
        "--write",
        action="store_true",
        help="insert CONFIRMED rows; without it, a CSV is written for review",
    )
    parser.add_argument(
        "--job-id",
        type=int,
        default=None,
        help="attach to a sweep_jobs row so the admin UI can show progress "
             "and pause/stop this run",
    )
    args = parser.parse_args()

    on_progress = should_stop = None
    if args.job_id is not None:
        from scraper.common.job_control import make_controls

        on_progress, should_stop = make_controls(args.job_id, "disclosures")

    summary = asyncio.run(
        run(
            limit=args.limit,
            start_appid=args.start_appid,
            only_appid=args.appid,
            write=args.write,
            on_progress=on_progress,
            should_stop=should_stop,
        )
    )
    if on_progress is not None:
        # Report the summary too, not just the periodic counters. Progress is
        # emitted every PROGRESS_EVERY games, so without this the recorded
        # walk position lags the real one by up to that many games and a
        # continuation re-reads them.
        asyncio.run(on_progress(summary))


if __name__ == "__main__":
    main()
