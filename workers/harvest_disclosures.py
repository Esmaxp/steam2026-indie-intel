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
SOURCE_PREFIX = "Developer announcement"


async def select_targets(limit: int, start_appid: int, only_appid: int | None) -> list[int]:
    """Upcoming and recently released games, appid order.

    Ordering by appid rather than a last-harvested timestamp keeps this
    resumable with --start-appid and needs no extra column: re-running is
    harmless anyway because ingestion is idempotent.
    """
    async with async_session_factory() as db:
        if only_appid is not None:
            return [only_appid]
        cutoff = datetime.date.today() - datetime.timedelta(days=365)
        stmt = (
            sa.select(Game.appid)
            .where(
                Game.appid >= start_appid,
                sa.or_(
                    Game.is_released.is_(False),
                    Game.release_date >= cutoff,
                ),
            )
            .order_by(Game.appid)
        )
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


async def run(limit: int, start_appid: int, only_appid: int | None, write: bool) -> dict:
    logger = setup_logging("harvest_disclosures")
    appids = await select_targets(limit, start_appid, only_appid)
    logger.info(
        "Scanning news for %s games at %.1fs%s",
        len(appids), MIN_INTERVAL, "" if write else " [dry-run]",
    )

    found: list[Disclosure] = []
    failed = 0
    async with make_session() as http:
        client = SteamClient(http, min_interval=MIN_INTERVAL)
        for appid in appids:
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

    summary = {
        "scanned": len(appids),
        "games_with_disclosures": len({d.appid for d in found}),
        "disclosures": len(found),
        "failed": failed,
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
    args = parser.parse_args()
    asyncio.run(
        run(
            limit=args.limit,
            start_appid=args.start_appid,
            only_appid=args.appid,
            write=args.write,
        )
    )


if __name__ == "__main__":
    main()
