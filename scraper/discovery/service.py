"""Discovery orchestration: find 2026 indie games, upsert them, checkpoint progress.

Two modes:

- search  (default) — Steam Search filtered to the Indie tag; a released pass
  sorted by release date DESC stops as soon as pages fall before the target
  year, and a coming-soon pass keeps rows whose date mentions the target year.
- applist — exhaustive GetAppList scan validated app-by-app via appdetails;
  resumable through sync_states, meant to run incrementally (--limit per run).

Both modes are idempotent: games are upserted on AppID, so re-runs never
create duplicates.
"""

import datetime
import logging

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from tqdm import tqdm

from app.db.session import async_session_factory
from app.models import Game, SyncStage, SyncStatus
from scraper.common.http import SteamClient, make_session
from scraper.common.sync import mark, pending_appids, register_pending
from scraper.discovery.applist import APP_LIST_URL, check_app, fetch_applist
from scraper.discovery.release_date import ParsedRelease, parse_release
from scraper.discovery.search import iter_search_pages

logger = logging.getLogger(__name__)

TARGET_YEAR = 2026
SEARCH_MIN_INTERVAL = 1.0      # seconds between Steam search requests
APPDETAILS_MIN_INTERVAL = 1.5  # seconds between appdetails requests


async def upsert_game(session, appid: int, name: str, release: ParsedRelease,
                      coming_soon: bool | None = None) -> None:
    is_released = release.date is not None and release.date <= datetime.date.today()
    if coming_soon is None:
        coming_soon = not is_released
    stmt = pg_insert(Game).values(
        appid=appid,
        name=name,
        steam_store_url=f"https://store.steampowered.com/app/{appid}/",
        steamdb_url=f"https://steamdb.info/app/{appid}/",
        release_date=release.date,
        release_date_raw=release.raw,
        is_released=is_released,
        coming_soon=coming_soon,
        is_indie=True,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Game.appid],
        set_={
            "name": name,
            "release_date": release.date,
            "release_date_raw": release.raw,
            "is_released": is_released,
            "coming_soon": coming_soon,
            "updated_at": func.now(),
        },
    )
    await session.execute(stmt)
    # Checkpoint: discovery finished, full store-data collection (Phase 3) queued.
    await mark(session, appid, SyncStage.DISCOVERY, SyncStatus.DONE)
    await register_pending(session, [appid], SyncStage.STORE_DATA)


async def run_search_discovery(max_pages: int = 2000) -> dict:
    """Fast discovery via Steam Search. Returns summary counters."""
    found = 0
    async with make_session() as http:
        client = SteamClient(http, min_interval=SEARCH_MIN_INTERVAL)

        # Pass 1 — released games, newest first; stop once a whole page
        # falls before the target year.
        logger.info("Search pass 1: released games (sorted by release date desc)")
        async with async_session_factory() as db:
            with tqdm(desc="released", unit="game") as bar:
                async for rows, _total in iter_search_pages(
                    client, {"sort_by": "Released_DESC"}, max_pages
                ):
                    page_years = []
                    for row in rows:
                        parsed = parse_release(row.release_text)
                        if parsed.year is not None:
                            page_years.append(parsed.year)
                        if parsed.year == TARGET_YEAR:
                            await upsert_game(db, row.appid, row.name, parsed)
                            found += 1
                            bar.update(1)
                    await db.commit()
                    if page_years and max(page_years) < TARGET_YEAR:
                        logger.info("Reached pre-%d releases — stopping pass 1", TARGET_YEAR)
                        break

        # Pass 2 — coming-soon games whose announced date mentions the target
        # year. Undated entries ("Coming soon", "TBA") are skipped: their year
        # is unknown and we never guess; re-runs pick them up once dated.
        logger.info("Search pass 2: coming-soon games")
        async with async_session_factory() as db:
            with tqdm(desc="coming soon", unit="game") as bar:
                async for rows, _total in iter_search_pages(
                    client, {"filter": "comingsoon"}, max_pages
                ):
                    for row in rows:
                        parsed = parse_release(row.release_text)
                        if parsed.year == TARGET_YEAR:
                            await upsert_game(db, row.appid, row.name, parsed, coming_soon=True)
                            found += 1
                            bar.update(1)
                    await db.commit()

    logger.info("Search discovery finished: %d games in %d catalog", found, TARGET_YEAR)
    return {"mode": "search", "found": found}


async def run_applist_discovery(limit: int = 500) -> dict:
    """Exhaustive, resumable App List scan. Validates `limit` pending apps per run."""
    async with make_session() as http:
        applist_client = SteamClient(http, min_interval=1.0)
        details_client = SteamClient(http, min_interval=APPDETAILS_MIN_INTERVAL)

        async with async_session_factory() as db:
            apps = await fetch_applist(applist_client)
            registered = await register_pending(
                db, [appid for appid, _ in apps], SyncStage.DISCOVERY
            )
            await db.commit()
            logger.info("Registered %d new discovery candidates from %s", registered, APP_LIST_URL)

            queue = await pending_appids(db, SyncStage.DISCOVERY, limit)

        kept = skipped = failed = 0
        async with async_session_factory() as db:
            for appid in tqdm(queue, desc="appdetails", unit="app"):
                try:
                    check = await check_app(details_client, appid, TARGET_YEAR)
                except Exception as exc:
                    failed += 1
                    await mark(db, appid, SyncStage.DISCOVERY, SyncStatus.FAILED, str(exc)[:500])
                    await db.commit()
                    logger.warning("appid %s failed: %s", appid, exc)
                    continue

                if check.keep:
                    await upsert_game(db, check.appid, check.name, check.release,
                                      coming_soon=check.coming_soon)
                    kept += 1
                else:
                    await mark(db, appid, SyncStage.DISCOVERY, SyncStatus.SKIPPED, check.reason)
                    skipped += 1
                await db.commit()

    logger.info(
        "App list discovery batch done: kept=%d skipped=%d failed=%d (resume with next run)",
        kept, skipped, failed,
    )
    return {"mode": "applist", "kept": kept, "skipped": skipped, "failed": failed}
