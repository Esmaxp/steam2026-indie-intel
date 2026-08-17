import math

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.serializers import build_detail, row_to_list_item, stats_point
from app.db.session import get_db
from app.models import (
    BudgetEstimate,
    Camera,
    DataStatus,
    Dimension,
    Festival,
    FollowerSnapshot,
    Game,
    GameEngine,
    GraphicsStyle,
    IndieConfidence,
    RevenueEstimate,
    RevenueRecord,
    SteamStats,
    Tag,
    WishlistRankEntry,
    WishlistRankSweep,
    WishlistRecord,
    game_festivals,
    game_tags,
)
from app.schemas.common import Page
from app.schemas.game import (
    FollowerPoint,
    GameDetail,
    GameListItem,
    GameSearchResult,
    RankPoint,
    StatsPoint,
)
from app.services.games_query import GameFilters, build_games_query
from app.services.similar_games import build_similar_query, fetch_source

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
    has_website: bool | None = Query(
        None, description="True = only games with an official website on record"
    ),
    has_videos: bool | None = Query(
        None, description="True = only games with cached community videos"
    ),
    next_fest: bool | None = None,
    release_status: str = Query(
        "all",
        pattern="^(released|upcoming|all)$",
        description="released = out now, upcoming = 2026-dated but not out yet",
    ),
    early_access: bool | None = None,
    free: bool | None = None,
    release_month: int | None = Query(None, ge=1, le=12),
    min_reviews: int | None = Query(None, ge=0),
    min_positive_pct: float | None = Query(None, ge=0, le=100),
    min_peak_ccu: int | None = Query(None, ge=0),
    min_revenue: float | None = Query(None, ge=0),
    min_followers: int | None = Query(
        None, ge=0, description="Steam community-hub followers — a measured value"
    ),
    ranked_only: bool | None = Query(
        None, description="only games on Valve's Top-Wishlists chart (~5.2k of all Steam)"
    ),
    max_wishlist_rank: int | None = Query(
        None, ge=1, description="keep games at or above this Top-Wishlists position"
    ),
    wishlist_status: DataStatus | None = None,
    revenue_status: DataStatus | None = None,
    indie_confidence: IndieConfidence | None = None,
    include_flagged: bool = Query(
        True, description="False hides games with the mass-publishing flag"
    ),
    effort_class: str | None = Query(
        None,
        pattern="^(serious|mixed|hobby|unknown)$",
        description="production effort the store page evidences — independent "
        "of whether the game sold",
    ),
    craft_class: str | None = Query(
        None,
        pattern="^(serious|mixed|hobby|unknown)$",
        description="production evidence only — screenshots, localisation, "
        "achievements, description. Blind to marketing, price and release "
        "status, so it is fair to free and unreleased games",
    ),
    classification: str | None = Query(
        None,
        pattern="^(HIGH_EFFORT_HIGH_TRACTION|HIGH_EFFORT_LOW_TRACTION|"
        "LOW_EFFORT_HIGH_TRACTION|LOW_EFFORT_LOW_TRACTION|INSUFFICIENT_DATA)$",
        description="the two axes crossed; HIGH_EFFORT_LOW_TRACTION is the "
        "serious-but-overlooked group",
    ),
    include_limited: bool = Query(
        True,
        description="False hides games whose Steam profile features are still "
        "restricted ('Steam is learning about this game')",
    ),
    sort: str = Query(
        "-release_date",
        description="column name, '-' prefix = descending; one of: appid, name, "
        "release_date, price, reviews, positive_pct, peak_ccu, videos, "
        "followers, follower_delta_14d, wishlist_rank, rank_delta_7d, revenue, "
        "copies. NOTE: wishlist_rank sorts ascending-is-better (rank 1 is the "
        "top of the chart). `revenue` orders on the ESTIMATED gross figure and "
        "is null for the ~2/3 of games with no estimate.",
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
) -> Page[GameListItem]:
    filters = GameFilters(
        q=q, developer=developer, publisher=publisher, genre=genre, tag=tag,
        engine=engine, dimension=dimension, camera=camera, graphics_style=graphics_style,
        demo_available=demo_available, has_website=has_website,
        has_videos=has_videos, next_fest=next_fest,
        release_status=release_status,
        early_access=early_access, free=free, release_month=release_month,
        min_reviews=min_reviews, min_positive_pct=min_positive_pct,
        min_peak_ccu=min_peak_ccu, min_revenue=min_revenue,
        min_followers=min_followers, ranked_only=ranked_only,
        max_wishlist_rank=max_wishlist_rank,
        wishlist_status=wishlist_status, revenue_status=revenue_status,
        indie_confidence=indie_confidence, include_flagged=include_flagged,
        effort_class=effort_class, craft_class=craft_class,
        classification=classification,
        include_limited=include_limited, sort=sort,
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


# NOTE: declared before /{appid} so the literal path wins route matching.
@router.get("/search", response_model=list[GameSearchResult])
async def search_games(
    db: AsyncSession = Depends(get_db),
    q: str = Query(..., min_length=2, description="name substring"),
    limit: int = Query(10, ge=1, le=25),
) -> list[GameSearchResult]:
    rows = (
        await db.execute(
            sa.select(Game.appid, Game.name)
            .where(Game.name.ilike(f"%{q}%"))
            .order_by(
                # prefix matches first, then shortest names (closest match)
                sa.case((Game.name.ilike(f"{q}%"), 0), else_=1),
                sa.func.length(Game.name),
                Game.appid,
            )
            .limit(limit)
        )
    ).all()
    return [GameSearchResult(appid=appid, name=name) for appid, name in rows]


@router.get("/{appid}/similar", response_model=list[GameListItem])
async def similar_games(
    appid: int,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(10, ge=1, le=50),
    include_flagged: bool = Query(
        False, description="mass-publishing-flagged games are excluded by default"
    ),
) -> list[GameListItem]:
    source = await fetch_source(db, appid)
    if source is None:
        raise HTTPException(status_code=404, detail="Game not found")
    stmt = build_similar_query(source, limit, include_flagged).options(*_GAME_LOAD_OPTIONS)
    rows = (await db.execute(stmt)).all()
    return [row_to_list_item(row) for row in rows]


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
                # Newest DISCLOSURE first. A harvest writes a game's whole
                # milestone history in one transaction, so recorded_at is
                # identical across rows and cannot order them.
                .order_by(
                    WishlistRecord.disclosed_on.desc().nullslast(),
                    WishlistRecord.recorded_at.desc(),
                )
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

    revenue_estimates = (
        (
            await db.execute(
                sa.select(RevenueEstimate)
                .where(RevenueEstimate.appid == appid)
                .order_by(RevenueEstimate.retrieved_at.desc(), RevenueEstimate.source_name)
            )
        )
        .scalars()
        .all()
    )

    budget_estimates = (
        (
            await db.execute(
                sa.select(BudgetEstimate)
                .where(BudgetEstimate.appid == appid)
                .order_by(BudgetEstimate.method)
            )
        )
        .scalars()
        .all()
    )

    return build_detail(
        row_to_list_item(row), game, tag_rows, festival_rows, latest,
        wishlist_history, revenue_history, revenue_estimates, budget_estimates,
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


async def _require_game(appid: int, db: AsyncSession) -> None:
    exists = (
        await db.execute(sa.select(Game.appid).where(Game.appid == appid))
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail="Game not found")


@router.get("/{appid}/followers", response_model=list[FollowerPoint])
async def get_game_followers(
    appid: int, db: AsyncSession = Depends(get_db)
) -> list[FollowerPoint]:
    """Community-hub follower history — measured, first-party, exact."""
    await _require_game(appid, db)
    rows = (
        (
            await db.execute(
                sa.select(FollowerSnapshot)
                .where(FollowerSnapshot.appid == appid)
                .order_by(FollowerSnapshot.captured_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return [
        FollowerPoint(
            captured_at=r.captured_at,
            followers=r.followers,
            source_name=r.source_name,
            source_url=r.source_url,
        )
        for r in rows
    ]


@router.get("/{appid}/rank-history", response_model=list[RankPoint])
async def get_game_rank_history(
    appid: int, db: AsyncSession = Depends(get_db)
) -> list[RankPoint]:
    """Valve Top-Wishlists position over time — an ORDER, never a count.

    Only COMPLETE sweeps are returned: a partial sweep holds just the head of
    the chart, so including one would look like the game dropped off it.
    """
    await _require_game(appid, db)
    rows = (
        await db.execute(
            sa.select(
                WishlistRankSweep.started_at,
                WishlistRankEntry.rank,
                WishlistRankSweep.rows_ingested,
                WishlistRankSweep.cc,
            )
            .join(WishlistRankEntry, WishlistRankEntry.sweep_id == WishlistRankSweep.id)
            .where(
                WishlistRankEntry.appid == appid,
                WishlistRankSweep.status == "complete",
            )
            .order_by(WishlistRankSweep.started_at.asc())
        )
    ).all()
    return [
        RankPoint(swept_at=started_at, rank=rank, total_ranked=rows_ingested, cc=cc)
        for started_at, rank, rows_ingested, cc in rows
    ]
