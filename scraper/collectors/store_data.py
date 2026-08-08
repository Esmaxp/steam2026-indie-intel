"""Phase 3 collector: full Steam store data + classification per queued game.

Consumes sync_states rows with stage=store_data, status=pending (queued by
discovery). For each game it collects appdetails, store-page tags, Steam Deck
compatibility and demo info, classifies the game, and normalizes everything
into the database. Finished games are queued for Phase 4 market data.

Honesty rules applied here:
- Steam page creation date is NOT exposed by Steam — left NULL (unknown).
- Developer/publisher country & website are NOT exposed by Steam — companies
  are created by name only; enrichment happens in Phase 4 from public sources.
- Launch price is only recorded when the game is observed within the first
  days after release; otherwise it stays NULL rather than being guessed
  from the current base price.
"""

import datetime
import logging
import re

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from tqdm import tqdm

from app.db.session import async_session_factory
from app.models import (
    ControllerSupport,
    Developer,
    Game,
    Genre,
    MarketingInfo,
    MediaAsset,
    MediaType,
    Publisher,
    SteamDeckSupport,
    SyncStage,
    SyncStatus,
    Tag,
    game_developers,
    game_genres,
    game_publishers,
    game_tags,
)
from scraper.classifiers.classify import classify
from scraper.classifiers.indie_signals import score_indie_signals
from scraper.classifiers.mass_publishing import flag_mass_publishing
from scraper.collectors.steam_sources import (
    AGE_GATE_COOKIES,
    fetch_appdetails,
    fetch_deck_category,
    fetch_demo_release_date,
    fetch_store_page_tags,
    parse_supported_languages,
)
from scraper.common.http import SteamClient, make_session
from scraper.common.sync import mark, pending_appids, register_pending
from scraper.discovery.release_date import parse_release

logger = logging.getLogger(__name__)

TARGET_YEAR = 2026
INDIE_GENRE_ID = "23"
EARLY_ACCESS_GENRE_ID = "70"
CATEGORY_FULL_CONTROLLER = 28
CATEGORY_PARTIAL_CONTROLLER = 18
LAUNCH_PRICE_WINDOW_DAYS = 7

APPDETAILS_MIN_INTERVAL = 1.5
STORE_PAGE_MIN_INTERVAL = 1.0

_DECK_CATEGORY_MAP = {
    1: SteamDeckSupport.UNSUPPORTED,
    2: SteamDeckSupport.PLAYABLE,
    3: SteamDeckSupport.VERIFIED,
}

_KICKSTARTER_RE = re.compile(
    r"https?://(?:www\.)?kickstarter\.com/projects/[^\s\"'<>)\]]+", re.I
)


async def _get_or_create_by_name(db: AsyncSession, model, name: str, **extra) -> int:
    stmt = pg_insert(model).values(name=name, **extra)
    stmt = stmt.on_conflict_do_nothing(index_elements=[model.name])
    await db.execute(stmt)
    result = await db.execute(sa.select(model.id).where(model.name == name))
    return result.scalar_one()


async def _replace_links(db: AsyncSession, table, appid: int, rows: list[dict]) -> None:
    await db.execute(sa.delete(table).where(table.c.appid == appid))
    if rows:
        await db.execute(sa.insert(table), rows)


async def _remove_game(db: AsyncSession, appid: int) -> None:
    await db.execute(sa.delete(Game).where(Game.appid == appid))


def _controller_support(details: dict) -> ControllerSupport:
    declared = (details.get("controller_support") or "").lower()
    if declared == "full":
        return ControllerSupport.FULL
    if declared == "partial":
        return ControllerSupport.PARTIAL
    category_ids = {c.get("id") for c in details.get("categories") or []}
    if CATEGORY_FULL_CONTROLLER in category_ids:
        return ControllerSupport.FULL
    if CATEGORY_PARTIAL_CONTROLLER in category_ids:
        return ControllerSupport.PARTIAL
    # Steam declares controller support explicitly; no declaration = none.
    return ControllerSupport.NONE


def _description_corpus(details: dict) -> str:
    return "\n".join(
        details.get(key) or ""
        for key in ("short_description", "about_the_game", "detailed_description")
    )


async def collect_one(
    db: AsyncSession,
    details_client: SteamClient,
    page_client: SteamClient,
    appid: int,
) -> tuple[SyncStatus, str]:
    """Collect one game. Returns (final status, reason)."""
    details = await fetch_appdetails(details_client, appid)
    if details is None:
        return SyncStatus.SKIPPED, "no_store_data"

    if details.get("type") != "game":
        await _remove_game(db, appid)
        return SyncStatus.SKIPPED, f"type_{details.get('type', 'unknown')}"

    release_info = details.get("release_date") or {}
    parsed = parse_release(release_info.get("date"))
    if parsed.year != TARGET_YEAR:
        # Release date moved out of 2026 since discovery — drop from catalog.
        await _remove_game(db, appid)
        return SyncStatus.SKIPPED, f"year_{parsed.year or 'unknown'}"

    genres = details.get("genres") or []
    if not any(
        str(g.get("id")) == INDIE_GENRE_ID or str(g.get("description", "")).lower() == "indie"
        for g in genres
    ):
        await _remove_game(db, appid)
        return SyncStatus.SKIPPED, "not_indie"

    # --- secondary Steam sources (each optional; failure → unknown) --------
    try:
        tags = await fetch_store_page_tags(page_client, appid)
    except Exception as exc:
        logger.warning("Store page tags failed for %s: %s", appid, exc)
        tags = []

    try:
        deck_support = _DECK_CATEGORY_MAP.get(
            await fetch_deck_category(page_client, appid), SteamDeckSupport.UNKNOWN
        )
    except Exception as exc:
        logger.warning("Deck report failed for %s: %s", appid, exc)
        deck_support = SteamDeckSupport.UNKNOWN

    demos = details.get("demos") or []
    demo_appid = demos[0].get("appid") if demos else None
    demo_release_date = None
    if demo_appid:
        try:
            demo_release_date = await fetch_demo_release_date(details_client, demo_appid)
        except Exception as exc:
            logger.warning("Demo appdetails failed for %s (demo %s): %s", appid, demo_appid, exc)

    # --- classification ----------------------------------------------------
    result = classify(
        tags,
        description=_description_corpus(details),
        legal_notice=details.get("legal_notice") or "",
    )

    # --- assemble the game row --------------------------------------------
    indie_signal = score_indie_signals(
        details.get("developers") or [], details.get("publishers") or []
    )
    coming_soon = bool(release_info.get("coming_soon"))
    is_released = not coming_soon and parsed.date is not None
    early_access = any(
        str(g.get("id")) == EARLY_ACCESS_GENRE_ID
        or str(g.get("description", "")).lower() == "early access"
        for g in genres
    )

    price = details.get("price_overview") or {}
    current_price = price.get("final")
    launch_price = None
    launch_discount = None
    if (
        parsed.date is not None
        and is_released
        and (datetime.date.today() - parsed.date).days <= LAUNCH_PRICE_WINDOW_DAYS
        and current_price is not None
    ):
        launch_price = current_price
        launch_discount = price.get("discount_percent")

    values = {
        "appid": appid,
        "name": details.get("name") or f"app_{appid}",
        "short_description": details.get("short_description"),
        "steam_store_url": f"https://store.steampowered.com/app/{appid}/",
        "steamdb_url": f"https://steamdb.info/app/{appid}/",
        "release_date": parsed.date,
        "release_date_raw": parsed.raw,
        "is_released": is_released,
        "coming_soon": coming_soon,
        "early_access": early_access,
        "demo_available": bool(demo_appid),
        "demo_appid": demo_appid,
        "demo_release_date": demo_release_date,
        "is_free": bool(details.get("is_free")),
        "currency": price.get("currency"),
        "current_price_cents": current_price,
        "launch_price_cents": launch_price,
        "launch_discount_pct": launch_discount,
        "controller_support": _controller_support(details),
        "steam_deck_support": deck_support,
        "supported_languages": parse_supported_languages(details.get("supported_languages")),
        "header_image_url": details.get("header_image"),
        "capsule_image_url": details.get("capsule_image") or details.get("capsule_imagev5"),
        "dimension": result.dimension,
        "camera": result.camera,
        "graphics_style": result.graphics_style,
        "engine": result.engine,
        # Base filter (Indie genre) passed; refine with publisher-size and
        # self-publishing signals. Major-publisher titles are flagged
        # (is_indie=False, confidence=low), never silently deleted.
        "is_indie": indie_signal.is_indie,
        "indie_confidence": indie_signal.confidence,
        "last_synced_at": sa.func.now(),
    }
    update_values = {k: v for k, v in values.items() if k != "appid"}
    update_values["updated_at"] = sa.func.now()
    stmt = pg_insert(Game).values(**values)
    stmt = stmt.on_conflict_do_update(index_elements=[Game.appid], set_=update_values)
    await db.execute(stmt)

    # --- companies (Steam gives names only; country stays unknown) ---------
    dev_ids = {}
    for name in details.get("developers") or []:
        if name.strip():
            dev_ids[await _get_or_create_by_name(db, Developer, name.strip())] = True
    await _replace_links(
        db, game_developers, appid,
        [{"appid": appid, "developer_id": i} for i in dev_ids],
    )

    # The store page's linked website is the developer's own site for
    # single-developer games; recorded with its provenance in notes.
    game_website = (details.get("website") or "").strip()
    if game_website and len(dev_ids) == 1 and "kickstarter.com" not in game_website:
        await db.execute(
            sa.update(Developer)
            .where(Developer.id == next(iter(dev_ids)), Developer.website.is_(None))
            .values(
                website=game_website,
                notes=sa.func.coalesce(
                    Developer.notes,
                    "Website from the game's Steam store page listing",
                ),
            )
        )

    pub_ids = {}
    for name in details.get("publishers") or []:
        if name.strip():
            pub_ids[await _get_or_create_by_name(db, Publisher, name.strip())] = True
    await _replace_links(
        db, game_publishers, appid,
        [{"appid": appid, "publisher_id": i} for i in pub_ids],
    )

    # --- genres & tags ------------------------------------------------------
    genre_ids = {}
    for genre in genres:
        genre_name = genre.get("description", "").strip()
        if genre_name:
            genre_ids[
                await _get_or_create_by_name(
                    db, Genre, genre_name, steam_genre_id=str(genre.get("id"))
                )
            ] = True
    await _replace_links(
        db, game_genres, appid,
        [{"appid": appid, "genre_id": i} for i in genre_ids],
    )

    tag_rows_by_id: dict[int, dict] = {}
    for rank, (tag_name, votes) in enumerate(tags, start=1):
        if not tag_name.strip():
            continue
        tag_id = await _get_or_create_by_name(db, Tag, tag_name.strip())
        tag_rows_by_id.setdefault(
            tag_id, {"appid": appid, "tag_id": tag_id, "rank": rank, "votes": votes}
        )
    await _replace_links(db, game_tags, appid, list(tag_rows_by_id.values()))

    # --- media assets (replace wholesale; Steam is the source of truth) ----
    await db.execute(sa.delete(MediaAsset).where(MediaAsset.appid == appid))
    media_rows: list[dict] = []
    if details.get("header_image"):
        media_rows.append(
            {"appid": appid, "media_type": MediaType.HEADER, "url": details["header_image"]}
        )
    capsule = details.get("capsule_image") or details.get("capsule_imagev5")
    if capsule:
        media_rows.append({"appid": appid, "media_type": MediaType.CAPSULE, "url": capsule})
    for shot in details.get("screenshots") or []:
        if shot.get("path_full"):
            media_rows.append(
                {
                    "appid": appid,
                    "media_type": MediaType.SCREENSHOT,
                    "url": shot["path_full"],
                    "thumbnail_url": shot.get("path_thumbnail"),
                    "position": shot.get("id"),
                }
            )
    for movie in details.get("movies") or []:
        url = (movie.get("mp4") or {}).get("max") or (movie.get("webm") or {}).get("max")
        if url:
            media_rows.append(
                {
                    "appid": appid,
                    "media_type": MediaType.MOVIE,
                    "url": url,
                    "thumbnail_url": movie.get("thumbnail"),
                    "position": movie.get("id"),
                }
            )
    if media_rows:
        await db.execute(sa.insert(MediaAsset), media_rows)

    # --- Kickstarter link, when the store page itself advertises one -------
    ks_match = _KICKSTARTER_RE.search(
        f"{details.get('website') or ''}\n{_description_corpus(details)}"
    )
    if ks_match:
        ks_url = ks_match.group(0).rstrip(".,")
        stmt = pg_insert(MarketingInfo).values(
            appid=appid,
            kickstarter_url=ks_url,
            source_name="Steam store page",
            source_url=values["steam_store_url"],
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[MarketingInfo.appid], set_={"kickstarter_url": ks_url}
        )
        await db.execute(stmt)

    # Queue Phase 4 market-data collection.
    await register_pending(db, [appid], SyncStage.MARKET_DATA)
    return SyncStatus.DONE, "ok"


async def run_store_collector(limit: int = 0, only_appid: int | None = None) -> dict:
    async with make_session() as http:
        http.cookie_jar.update_cookies(AGE_GATE_COOKIES)
        details_client = SteamClient(http, min_interval=APPDETAILS_MIN_INTERVAL)
        page_client = SteamClient(http, min_interval=STORE_PAGE_MIN_INTERVAL)

        async with async_session_factory() as db:
            if only_appid is not None:
                queue = [only_appid]
            else:
                queue = await pending_appids(db, SyncStage.STORE_DATA, limit)

        done = skipped = failed = 0
        async with async_session_factory() as db:
            for appid in tqdm(queue, desc="store data", unit="game"):
                try:
                    status, reason = await collect_one(db, details_client, page_client, appid)
                except Exception as exc:
                    status, reason = SyncStatus.FAILED, str(exc)[:500]
                    logger.warning("appid %s failed: %s", appid, exc)
                await mark(db, appid, SyncStage.STORE_DATA, status,
                           None if reason == "ok" else reason)
                await db.commit()
                if status is SyncStatus.DONE:
                    done += 1
                elif status is SyncStatus.SKIPPED:
                    skipped += 1
                else:
                    failed += 1

    logger.info("Store collector batch: done=%d skipped=%d failed=%d", done, skipped, failed)

    if done:
        try:
            flagged = await flag_mass_publishing()
            logger.info("Mass-publishing recheck after batch: %d flagged", flagged)
        except Exception as exc:
            logger.warning("Mass-publishing pass failed: %s", exc)

    return {"done": done, "skipped": skipped, "failed": failed, "queued": len(queue)}
