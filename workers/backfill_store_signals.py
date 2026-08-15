"""One-off backfill: the store-page and appdetails fields nobody was keeping.

Four things the catalogue needs and does not have, because store_data never
re-runs for a game once it is DONE:

- `limited_profile` — Valve's "Steam is learning about this game" banner, the
  single most reliable low-traction signal available publicly. Printed on the
  store page, absent from appdetails.
- `ai_disclosure` — the generative-AI declaration, mandatory since Jan 2024.
  Recorded, never scored.
- `list_price_cents` — Steam's list price. The collector only kept `final`,
  which moves with every sale, so no rule could tell a $2 game from a $20 one
  during a 90% discount.
- trailers — `movies` entries were being read from `mp4`/`webm` keys Steam has
  since removed, so every trailer in the catalogue was silently dropped. The
  parser is fixed; this pass rewrites the media rows that were lost.

Two requests per game (appdetails + store page) at the collector's own pacing.
Resumable in the same way workers/refresh_followers.py is: oldest-unchecked
first, committed in batches, so an interrupted run simply continues.

Usage:
    python -m workers.backfill_store_signals [--limit 500] [--include-checked]
    docker compose run --rm store_signals
"""

import argparse
import asyncio

import sqlalchemy as sa

from app.db.session import async_session_factory
from app.models import Game, MediaAsset, MediaType
from scraper.collectors.steam_sources import fetch_appdetails, fetch_store_page
from scraper.collectors.store_data import _movie_url
from scraper.common.http import NonRetryableHTTPError, SteamClient, make_session
from scraper.common.logging import setup_logging

APPDETAILS_MIN_INTERVAL = 1.5
STORE_PAGE_MIN_INTERVAL = 1.5
COMMIT_EVERY = 50
PROGRESS_EVERY = 100


async def select_targets(limit: int, include_checked: bool, sample: bool) -> list[int]:
    async with async_session_factory() as db:
        stmt = sa.select(Game.appid)
        if not include_checked:
            # limited_profile is written on every pass, so NULL is exactly the
            # set this worker has not reached yet.
            stmt = stmt.where(Game.limited_profile.is_(None))
        # appid order correlates with age: the low end is years-old catalogue
        # entries, which are systematically more produced than a 2026 upload.
        # Sampling randomly is the only way to measure a signal's real
        # prevalence before trusting it as a weight.
        stmt = stmt.order_by(sa.func.random() if sample else Game.appid)
        if limit:
            stmt = stmt.limit(limit)
        return list((await db.execute(stmt)).scalars().all())


async def _replace_movies(db, appid: int, details: dict) -> int:
    """Rewrite this game's trailer rows; screenshots and art are untouched."""
    await db.execute(
        sa.delete(MediaAsset).where(
            MediaAsset.appid == appid, MediaAsset.media_type == MediaType.MOVIE
        )
    )
    rows = []
    for movie in details.get("movies") or []:
        url = _movie_url(movie)
        if url:
            rows.append(
                {
                    "appid": appid,
                    "media_type": MediaType.MOVIE,
                    "url": url,
                    "thumbnail_url": movie.get("thumbnail"),
                    "position": movie.get("id"),
                }
            )
    if rows:
        await db.execute(sa.insert(MediaAsset), rows)
    return len(rows)


async def run(limit: int, include_checked: bool, sample: bool) -> None:
    logger = setup_logging("backfill_store_signals")
    appids = await select_targets(limit, include_checked, sample)
    if not appids:
        logger.info("Nothing left to backfill — every game has been checked.")
        return
    logger.info("Backfilling store signals for %d games (2 requests each)", len(appids))

    limited = disclosed = with_trailer = failed = 0
    async with make_session() as details_session, make_session() as page_session:
        details_client = SteamClient(details_session, min_interval=APPDETAILS_MIN_INTERVAL)
        page_client = SteamClient(page_session, min_interval=STORE_PAGE_MIN_INTERVAL)

        db = async_session_factory()
        try:
            for index, appid in enumerate(appids, start=1):
                try:
                    details = await fetch_appdetails(details_client, appid)
                except (NonRetryableHTTPError, asyncio.TimeoutError) as exc:
                    logger.warning("appdetails failed for %s: %s", appid, exc)
                    failed += 1
                    continue
                if details is None:
                    # Delisted or region-locked since collection; leave the row
                    # untouched rather than writing misleading False flags.
                    failed += 1
                    continue

                try:
                    _, flags = await fetch_store_page(page_client, appid)
                except Exception as exc:  # page shapes vary; never abort the run
                    logger.warning("store page failed for %s: %s", appid, exc)
                    failed += 1
                    continue

                price = details.get("price_overview") or {}
                values = {
                    "limited_profile": flags.limited_profile,
                    "ai_disclosure": flags.ai_disclosure,
                    "achievements_count": (details.get("achievements") or {}).get("total"),
                }
                if price.get("initial") is not None:
                    values["list_price_cents"] = price["initial"]

                await db.execute(sa.update(Game).where(Game.appid == appid).values(**values))
                movies = await _replace_movies(db, appid, details)

                limited += int(flags.limited_profile)
                disclosed += int(flags.ai_disclosure)
                with_trailer += int(movies > 0)

                if index % COMMIT_EVERY == 0:
                    await db.commit()
                if index % PROGRESS_EVERY == 0 or index == len(appids):
                    logger.info(
                        "Progress %d/%d — limited %d, ai-disclosed %d, "
                        "with trailer %d, failed %d",
                        index, len(appids), limited, disclosed, with_trailer, failed,
                    )
            await db.commit()
        finally:
            await db.close()

    logger.info(
        "Done: %d games checked — %d Steam-limited, %d AI-disclosed, "
        "%d have a trailer, %d could not be read.",
        len(appids), limited, disclosed, with_trailer, failed,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill limited-profile, AI disclosure, list price and trailers"
    )
    parser.add_argument("--limit", type=int, default=0,
                        help="max games this run; 0 = all remaining (default)")
    parser.add_argument("--include-checked", action="store_true",
                        help="re-check games that already have the flags (refresh)")
    parser.add_argument("--sample", action="store_true",
                        help="pick randomly instead of oldest-first — use with "
                             "--limit to measure a signal's prevalence")
    args = parser.parse_args()
    asyncio.run(run(args.limit, args.include_checked, args.sample))


if __name__ == "__main__":
    main()
