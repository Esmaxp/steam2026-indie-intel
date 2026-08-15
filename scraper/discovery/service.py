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

import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from tqdm import tqdm

from app.db.session import async_session_factory
from app.models import Game, SyncStage, SyncState, SyncStatus
from scraper.common.http import SteamClient, make_session
from scraper.common.sync import mark, pending_appids, register_pending
from scraper.discovery.applist import APP_LIST_URL, check_app, fetch_applist
from scraper.discovery.release_date import ParsedRelease, parse_release
from scraper.discovery.search import iter_search_pages

logger = logging.getLogger(__name__)

TARGET_YEAR = 2026
SEARCH_MIN_INTERVAL = 1.0      # seconds between Steam search requests
APPDETAILS_MIN_INTERVAL = 1.5  # seconds between appdetails requests


def release_flags(
    release: ParsedRelease, coming_soon: bool | None, today: datetime.date
) -> tuple[bool, bool]:
    """(is_released, coming_soon) — mutually exclusive, always.

    Steam's own `coming_soon` wins when we have it: a game whose listed date
    has passed but which Valve still flags as upcoming has not launched (dates
    slip, and the flag clears at the real launch, not at midnight). Deriving
    the two flags independently let both be true at once, and because a later
    re-discovery upserts over the collector's value, those rows survived —
    which is how the "upcoming" tile and the upcoming filter came to disagree.

    Pure so the invariant can be tested without a database.
    """
    if coming_soon is not None:
        return (not coming_soon and release.date is not None), coming_soon
    is_released = release.date is not None and release.date <= today
    return is_released, not is_released


async def upsert_game(session, appid: int, name: str, release: ParsedRelease,
                      coming_soon: bool | None = None,
                      discovery_method: str = "indie_tag") -> None:
    is_released, coming_soon = release_flags(
        release, coming_soon, datetime.date.today()
    )
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
        # Audit trail; deliberately NOT in the conflict-update set below —
        # the first admission path wins, re-discovery never rewrites it.
        discovery_method=discovery_method,
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
                        # Audit trail: raw release text per row (LOG_LEVEL=DEBUG)
                        logger.debug(
                            "search row appid=%s release_text=%r", row.appid, row.release_text
                        )
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
                        logger.debug(
                            "search row appid=%s release_text=%r", row.appid, row.release_text
                        )
                        parsed = parse_release(row.release_text)
                        if parsed.year == TARGET_YEAR:
                            await upsert_game(db, row.appid, row.name, parsed, coming_soon=True)
                            found += 1
                            bar.update(1)
                    await db.commit()

    logger.info("Search discovery finished: %d games in %d catalog", found, TARGET_YEAR)
    return {"mode": "search", "found": found}


async def run_untagged_search_discovery(max_pages: int = 2000) -> dict:
    """Tag-less discovery via Steam Search — no dependency on GetAppList.

    Scans ALL 2026 games (Indie tag filter removed) with the same date-sorted
    early-stop paging as run_search_discovery, then validates only the
    candidates the catalog doesn't already know via appdetails +
    evaluate_app(include_untagged=True) — the exact same admission rules as
    the applist fallback (self-published / boutique label only; the generic
    third-party MEDIUM branch stays excluded).

    Resumable: accepted games mark DISCOVERY done; rejected candidates mark
    DISCOVERY skipped with the reason, so re-runs never re-fetch them.
    """
    counters = {"pages": 0, "checked": 0, "rejected": 0, "failed": 0}
    kept: dict[str, int] = {}

    async with make_session() as http:
        search_client = SteamClient(http, min_interval=SEARCH_MIN_INTERVAL)
        details_client = SteamClient(http, min_interval=APPDETAILS_MIN_INTERVAL)

        async def process_candidates(db, rows) -> None:
            """rows: SearchRows already parsed to the target year."""
            appids = [row.appid for row in rows]
            if not appids:
                return
            known = set(
                (await db.execute(sa.select(Game.appid).where(Game.appid.in_(appids))))
                .scalars()
                .all()
            )
            evaluated = set(
                (
                    await db.execute(
                        sa.select(SyncState.appid).where(
                            SyncState.stage == SyncStage.DISCOVERY,
                            SyncState.appid.in_(appids),
                            SyncState.status.in_([SyncStatus.DONE, SyncStatus.SKIPPED]),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                if row.appid in known or row.appid in evaluated:
                    continue
                try:
                    check = await check_app(
                        details_client, row.appid, TARGET_YEAR, include_untagged=True
                    )
                except Exception as exc:
                    counters["failed"] += 1
                    await mark(
                        db, row.appid, SyncStage.DISCOVERY, SyncStatus.FAILED, str(exc)[:500]
                    )
                    continue
                counters["checked"] += 1
                if check.keep:
                    await upsert_game(
                        db, check.appid, check.name, check.release,
                        coming_soon=check.coming_soon,
                        discovery_method=check.discovery_method,
                    )
                    kept[check.discovery_method] = kept.get(check.discovery_method, 0) + 1
                else:
                    counters["rejected"] += 1
                    await mark(
                        db, row.appid, SyncStage.DISCOVERY, SyncStatus.SKIPPED, check.reason
                    )
            await db.commit()

        # Pass 1 — released games of every genre, newest first; stop once a
        # whole page falls before the target year (same rule as the tagged pass).
        logger.info("Untagged pass 1: released games (no Indie tag filter)")
        async with async_session_factory() as db:
            async for rows, _total in iter_search_pages(
                search_client, {"sort_by": "Released_DESC", "tags": ""}, max_pages
            ):
                counters["pages"] += 1
                page_years = []
                candidates = []
                for row in rows:
                    parsed = parse_release(row.release_text)
                    if parsed.year is not None:
                        page_years.append(parsed.year)
                    if parsed.year == TARGET_YEAR:
                        candidates.append(row)
                await process_candidates(db, candidates)
                if counters["pages"] % 25 == 0:
                    logger.info(
                        "Untagged progress: %d pages — checked %d, kept %s, rejected %d",
                        counters["pages"], counters["checked"], kept, counters["rejected"],
                    )
                if page_years and max(page_years) < TARGET_YEAR:
                    logger.info("Reached pre-%d releases — stopping pass 1", TARGET_YEAR)
                    break

        # Pass 2 — coming-soon games whose announced date names the target year.
        logger.info("Untagged pass 2: coming-soon games (no Indie tag filter)")
        async with async_session_factory() as db:
            async for rows, _total in iter_search_pages(
                search_client, {"filter": "comingsoon", "tags": ""}, max_pages
            ):
                counters["pages"] += 1
                candidates = [
                    row for row in rows if parse_release(row.release_text).year == TARGET_YEAR
                ]
                await process_candidates(db, candidates)
                if counters["pages"] % 25 == 0:
                    logger.info(
                        "Untagged progress: %d pages — checked %d, kept %s, rejected %d",
                        counters["pages"], counters["checked"], kept, counters["rejected"],
                    )

    summary = {"mode": "search_untagged", **counters, "kept": kept}
    logger.info(
        "Untagged search discovery finished: %d pages, %d candidates checked, "
        "kept %s, rejected %d, failed %d",
        counters["pages"], counters["checked"], kept,
        counters["rejected"], counters["failed"],
    )
    return summary


async def run_targeted_discovery(appids: list[int]) -> dict:
    """Check specific AppIDs without a full scan — for freshly listed games
    the search passes missed (Steam-side indexing lag) or games previously
    skipped whose metadata has since changed.

    Runs the full Phase 3 store validation/collection directly (appdetails +
    store tags + classification), so the game lands complete and queued for
    market data — the never-guess-a-date rule applies unchanged."""
    from scraper.collectors.store_data import (
        APPDETAILS_MIN_INTERVAL as DETAILS_INTERVAL,
        STORE_PAGE_MIN_INTERVAL as PAGE_INTERVAL,
        collect_one,
    )
    from scraper.collectors.steam_sources import AGE_GATE_COOKIES

    results: dict[int, str] = {}
    async with make_session() as http:
        http.cookie_jar.update_cookies(AGE_GATE_COOKIES)
        details_client = SteamClient(http, min_interval=DETAILS_INTERVAL)
        page_client = SteamClient(http, min_interval=PAGE_INTERVAL)

        async with async_session_factory() as db:
            for appid in appids:
                try:
                    status, reason = await collect_one(db, details_client, page_client, appid)
                except Exception as exc:
                    status, reason = SyncStatus.FAILED, str(exc)[:200]
                    logger.warning("Targeted check failed for %s: %s", appid, exc)
                await mark(db, appid, SyncStage.DISCOVERY, status)
                await mark(db, appid, SyncStage.STORE_DATA, status,
                           None if reason == "ok" else reason)
                await db.commit()
                results[appid] = f"{status.value} ({reason})"
                logger.info("Targeted %s -> %s", appid, results[appid])
    return {"mode": "targeted", "results": results}


async def run_applist_discovery(limit: int = 500, include_untagged: bool = False) -> dict:
    """Exhaustive, resumable App List scan. Validates `limit` pending apps per run.

    include_untagged=False keeps today's behavior exactly (Indie tag mandatory).
    True additionally admits tag-less games with a self-published or boutique-
    label publisher signal (see applist.evaluate_app)."""
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
                    check = await check_app(
                        details_client, appid, TARGET_YEAR, include_untagged
                    )
                except Exception as exc:
                    failed += 1
                    await mark(db, appid, SyncStage.DISCOVERY, SyncStatus.FAILED, str(exc)[:500])
                    await db.commit()
                    logger.warning("appid %s failed: %s", appid, exc)
                    continue

                if check.keep:
                    await upsert_game(db, check.appid, check.name, check.release,
                                      coming_soon=check.coming_soon,
                                      discovery_method=check.discovery_method)
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
