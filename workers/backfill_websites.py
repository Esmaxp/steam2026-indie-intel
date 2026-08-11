"""Low-priority background job: fill games.website from Steam appdetails.

Steam's free public appdetails endpoint exposes an official `website` field.
This worker slowly walks games whose website was never checked
(website IS NULL — '' means "checked, none listed") and records it. It is
rate-limited (same interval as the store collector) and safe to run daily or
in small batches over days.

Usage:
    python -m workers.backfill_websites [--limit 300]
    docker compose run --rm websites
"""

import argparse
import asyncio

import sqlalchemy as sa

from app.db.session import async_session_factory
from app.models import Game
from scraper.collectors.steam_sources import fetch_appdetails
from scraper.common.http import NonRetryableHTTPError, SteamClient, make_session
from scraper.common.logging import setup_logging

APPDETAILS_MIN_INTERVAL = 1.5  # matches the store collector's pacing


async def run(limit: int) -> None:
    logger = setup_logging("backfill_websites")
    async with async_session_factory() as db:
        appids = (
            (
                await db.execute(
                    sa.select(Game.appid)
                    .where(Game.website.is_(None))
                    .order_by(Game.appid)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
    if not appids:
        logger.info("No games left to check — websites are up to date.")
        return
    logger.info("Checking %d games for an official website", len(appids))

    found = 0
    async with make_session() as session:
        client = SteamClient(session, min_interval=APPDETAILS_MIN_INTERVAL)
        for appid in appids:
            try:
                details = await fetch_appdetails(client, appid)
            except NonRetryableHTTPError as exc:
                logger.warning("appdetails failed for %s: %s", appid, exc)
                continue
            website = ((details or {}).get("website") or "").strip()
            if website:
                found += 1
            async with async_session_factory() as db:
                await db.execute(
                    sa.update(Game).where(Game.appid == appid).values(website=website)
                )
                await db.commit()
    logger.info("Done: %d/%d games had a website listed", found, len(appids))


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill games.website from Steam appdetails")
    parser.add_argument(
        "--limit", type=int, default=300,
        help="max games to check this run (keep small; runs fine over days)",
    )
    args = parser.parse_args()
    asyncio.run(run(args.limit))


if __name__ == "__main__":
    main()
