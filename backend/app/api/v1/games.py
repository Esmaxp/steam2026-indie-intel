import math

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.serializers import build_detail, row_to_list_item, stats_point
from app.db.session import get_db
from app.models import (
    Camera,
    DataStatus,
    Dimension,
    Festival,
    Game,
    GameEngine,
    GraphicsStyle,
    IndieConfidence,
    RevenueRecord,
    SteamStats,
    Tag,
    WishlistRecord,
    game_festivals,
    game_tags,
)
from app.schemas.common import Page
from app.schemas.game import GameDetail, GameListItem, StatsPoint
from app.services.games_query import GameFilters, build_games_query

router = APIRouter()

_GAME_LOAD_OPTIONS = (
    selectinload(Game.developers),
    selectinload(Game.publishers),
    selectinload(Game.genres),
    selectinload(Game.tags),
)


@router.get("", response_model=Page[GameListItem])
async def list_games(
    db: AsyncSession = Depends(get_db),
    q: str | None = Query(None, description="search in game name"),
    developer: str | None = None,
    publisher: str | None = None,
    genre: str | None = None,
    tag: str | None = None,
    engine: GameEngine | None = None,
    dimension: Dimension | None = None,
    camera: Camera | None = None,
    graphics_style: GraphicsStyle | None = None,
    demo_available: bool | None = None,
    next_fest: bool | None = None,
    released: bool | None = None,
    early_access: bool | None = None,
    free: bool | None = None,
    release_month: int | None = Query(None, ge=1, le=12),
    min_reviews: int | None = Query(None, ge=0),
    min_positive_pct: float | None = Query(None, ge=0, le=100),
    min_peak_ccu: int | None = Query(None, ge=0),
    min_wishlist: int | None = Query(None, ge=0),
    min_revenue: float | None = Query(None, ge=0),
    wishlist_status: DataStatus | None = None,
    revenue_status: DataStatus | None = None,
    indie_confidence: IndieConfidence | None = None,
    include_flagged: bool = Query(
        True, description="False hides games with the mass-publishing flag"
    ),
    sort: str = Query(
        "-release_date",
        description="column name, '-' prefix = descending; one of: appid, name, "
        "release_date, price, reviews, positive_pct, peak_ccu, wishlist, revenue",
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
) -> Page[GameListItem]:
    filters = GameFilters(
        q=q, developer=developer, publisher=publisher, genre=genre, tag=tag,
        engine=engine, dimension=dimension, camera=camera, graphics_style=graphics_style,
        demo_available=demo_available, next_fest=next_fest, released=released,
        early_access=early_access, free=free, release_month=release_month,
        min_reviews=min_reviews, min_positive_pct=min_positive_pct,
        min_peak_ccu=min_peak_ccu, min_wishlist=min_wishlist, min_revenue=min_revenue,
        wishlist_status=wishlist_status, revenue_status=revenue_status,
        indie_confidence=indie_confidence, include_flagged=include_flagged, sort=sort,
    )
    query = build_games_query(filters)

    total = (await db.execute(query.count_stmt)).scalar_one()
    stmt = (
        query.stmt.options(*_GAME_LOAD_OPTIONS)
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    rows = (await db.execute(stmt)).all()

    return Page(
        items=[row_to_list_item(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, math.ceil(total / page_size)),
    )


@router.get("/{appid}", response_model=GameDetail)
async def get_game(appid: int, db: AsyncSession = Depends(get_db)) -> GameDetail:
    # Reuse the list query for the joined latest-values columns.
    query = build_games_query(GameFilters())
    stmt = (
        query.stmt.where(Game.appid == appid)
        .options(
            *_GAME_LOAD_OPTIONS,
            selectinload(Game.media_assets),
            selectinload(Game.marketing_info),
        )
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Game not found")
    game: Game = row.Game

    tag_rows = (
        await db.execute(
            sa.select(Tag.name, game_tags.c.rank, game_tags.c.votes)
            .join(game_tags, game_tags.c.tag_id == Tag.id)
            .where(game_tags.c.appid == appid)
            .order_by(game_tags.c.rank)
        )
    ).all()

    festival_rows = (
        await db.execute(
            sa.select(
                Festival.name,
                Festival.is_next_fest,
                Festival.start_date,
                Festival.end_date,
                game_festivals.c.source_url,
                game_festivals.c.notes,
            )
            .join(game_festivals, game_festivals.c.festival_id == Festival.id)
            .where(game_festivals.c.appid == appid)
        )
    ).all()

    latest = (
        await db.execute(
            sa.select(SteamStats)
            .where(SteamStats.appid == appid)
            .order_by(SteamStats.captured_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    wishlist_history = (
        (
            await db.execute(
                sa.select(WishlistRecord)
                .where(WishlistRecord.appid == appid)
                .order_by(WishlistRecord.recorded_at.desc())
            )
        )
        .scalars()
        .all()
    )
    revenue_history = (
        (
            await db.execute(
                sa.select(RevenueRecord)
                .where(RevenueRecord.appid == appid)
                .order_by(RevenueRecord.recorded_at.desc())
            )
        )
        .scalars()
        .all()
    )

    return build_detail(
        row_to_list_item(row), game, tag_rows, festival_rows, latest,
        wishlist_history, revenue_history,
    )


@router.get("/{appid}/stats", response_model=list[StatsPoint])
async def get_game_stats(appid: int, db: AsyncSession = Depends(get_db)) -> list[StatsPoint]:
    exists = (
        await db.execute(sa.select(Game.appid).where(Game.appid == appid))
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail="Game not found")
    points = (
        (
            await db.execute(
                sa.select(SteamStats)
                .where(SteamStats.appid == appid)
                .order_by(SteamStats.captured_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return [stats_point(p) for p in points]
