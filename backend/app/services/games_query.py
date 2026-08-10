"""Shared query builder for the games list, dashboard and (Phase 8) exports.

Latest-per-game values come from PostgreSQL DISTINCT ON subqueries.
Wishlist/revenue "latest" prefers confirmed over estimated records
(the data_status enum is ordered confirmed < estimated < unknown),
then the most recent observation.
"""

from dataclasses import dataclass

import sqlalchemy as sa

from app.models import (
    Camera,
    DataStatus,
    Developer,
    Dimension,
    Festival,
    Game,
    GameEngine,
    Genre,
    GraphicsStyle,
    IndieConfidence,
    MarketingInfo,
    Publisher,
    RevenueRecord,
    SteamStats,
    Tag,
    WishlistRecord,
    game_festivals,
)


def latest_stats_sq():
    return (
        sa.select(SteamStats)
        .distinct(SteamStats.appid)
        .order_by(SteamStats.appid, SteamStats.captured_at.desc())
        .subquery("latest_stats")
    )


def latest_wishlist_sq():
    return (
        sa.select(WishlistRecord)
        .distinct(WishlistRecord.appid)
        .order_by(
            WishlistRecord.appid, WishlistRecord.status, WishlistRecord.recorded_at.desc()
        )
        .subquery("latest_wishlist")
    )


def latest_revenue_sq():
    return (
        sa.select(RevenueRecord)
        .distinct(RevenueRecord.appid)
        .order_by(
            RevenueRecord.appid, RevenueRecord.status, RevenueRecord.recorded_at.desc()
        )
        .subquery("latest_revenue")
    )


def next_fest_exists():
    return sa.exists(
        sa.select(sa.literal(1))
        .select_from(
            game_festivals.join(Festival, game_festivals.c.festival_id == Festival.id)
        )
        .where(game_festivals.c.appid == Game.appid, Festival.is_next_fest.is_(True))
    )


@dataclass
class GameFilters:
    q: str | None = None
    developer: str | None = None
    publisher: str | None = None
    genre: str | None = None
    tag: str | None = None
    engine: GameEngine | None = None
    dimension: Dimension | None = None
    camera: Camera | None = None
    graphics_style: GraphicsStyle | None = None
    demo_available: bool | None = None
    next_fest: bool | None = None
    release_status: str = "all"  # released | upcoming | all
    early_access: bool | None = None
    free: bool | None = None
    release_month: int | None = None
    min_reviews: int | None = None
    min_positive_pct: float | None = None
    min_peak_ccu: int | None = None
    min_wishlist: int | None = None
    min_revenue: float | None = None
    wishlist_status: DataStatus | None = None
    revenue_status: DataStatus | None = None
    indie_confidence: IndieConfidence | None = None
    include_flagged: bool = True  # False hides low_quality_signal games
    sort: str = "-release_date"


@dataclass
class GamesQuery:
    stmt: sa.Select
    count_stmt: sa.Select


def build_games_query(f: GameFilters) -> GamesQuery:
    ls, lw, lr = latest_stats_sq(), latest_wishlist_sq(), latest_revenue_sq()
    nf = next_fest_exists()

    stmt = (
        sa.select(
            Game,
            ls.c.total_reviews.label("total_reviews"),
            ls.c.positive_pct.label("positive_pct"),
            ls.c.review_score_desc.label("review_score_desc"),
            ls.c.peak_ccu.label("peak_ccu"),
            ls.c.avg_ccu.label("avg_ccu"),
            lw.c.wishlist_count.label("wishlist_count"),
            lw.c.status.label("wishlist_status"),
            lw.c.source_name.label("wishlist_source"),
            lw.c.source_url.label("wishlist_source_url"),
            lw.c.recorded_at.label("wishlist_recorded_at"),
            lr.c.gross_revenue_usd.label("revenue_gross"),
            lr.c.estimated_sales.label("estimated_sales"),
            lr.c.estimate_spread.label("revenue_spread"),
            lr.c.status.label("revenue_status"),
            lr.c.source_name.label("revenue_source"),
            lr.c.source_url.label("revenue_source_url"),
            lr.c.recorded_at.label("revenue_recorded_at"),
            MarketingInfo.budget_estimate_usd.label("budget_value"),
            MarketingInfo.budget_status.label("budget_status"),
            MarketingInfo.source_name.label("budget_source"),
            MarketingInfo.source_url.label("budget_source_url"),
            nf.label("next_fest"),
        )
        .outerjoin(ls, ls.c.appid == Game.appid)
        .outerjoin(lw, lw.c.appid == Game.appid)
        .outerjoin(lr, lr.c.appid == Game.appid)
        .outerjoin(MarketingInfo, MarketingInfo.appid == Game.appid)
    )

    conds = []
    if f.q:
        conds.append(Game.name.ilike(f"%{f.q}%"))
    if f.developer:
        conds.append(Game.developers.any(Developer.name.ilike(f"%{f.developer}%")))
    if f.publisher:
        conds.append(Game.publishers.any(Publisher.name.ilike(f"%{f.publisher}%")))
    if f.genre:
        conds.append(Game.genres.any(sa.func.lower(Genre.name) == f.genre.lower()))
    if f.tag:
        conds.append(Game.tags.any(sa.func.lower(Tag.name) == f.tag.lower()))
    if f.engine is not None:
        conds.append(Game.engine == f.engine)
    if f.dimension is not None:
        conds.append(Game.dimension == f.dimension)
    if f.camera is not None:
        conds.append(Game.camera == f.camera)
    if f.graphics_style is not None:
        conds.append(Game.graphics_style == f.graphics_style)
    if f.demo_available is not None:
        conds.append(Game.demo_available.is_(f.demo_available))
    if f.next_fest is not None:
        conds.append(nf if f.next_fest else sa.not_(nf))
    if f.release_status == "released":
        conds.append(Game.is_released.is_(True))
    elif f.release_status == "upcoming":
        conds.append(Game.is_released.is_(False))
    if f.early_access is not None:
        conds.append(Game.early_access.is_(f.early_access))
    if f.free is not None:
        conds.append(Game.is_free.is_(f.free))
    if f.release_month is not None:
        conds.append(sa.extract("month", Game.release_date) == f.release_month)
    if f.indie_confidence is not None:
        conds.append(Game.indie_confidence == f.indie_confidence)
    if not f.include_flagged:
        conds.append(Game.low_quality_signal.is_(False))
    if f.min_reviews is not None:
        conds.append(ls.c.total_reviews >= f.min_reviews)
    if f.min_positive_pct is not None:
        conds.append(ls.c.positive_pct >= f.min_positive_pct)
    if f.min_peak_ccu is not None:
        conds.append(ls.c.peak_ccu >= f.min_peak_ccu)
    if f.min_wishlist is not None:
        conds.append(lw.c.wishlist_count >= f.min_wishlist)
    if f.min_revenue is not None:
        conds.append(lr.c.gross_revenue_usd >= f.min_revenue)
    if f.wishlist_status is not None:
        if f.wishlist_status is DataStatus.UNKNOWN:
            # Unknown = no record at all, or an explicit unknown record.
            conds.append(
                sa.or_(lw.c.status.is_(None), lw.c.status == DataStatus.UNKNOWN)
            )
        else:
            conds.append(lw.c.status == f.wishlist_status)
    if f.revenue_status is not None:
        if f.revenue_status is DataStatus.UNKNOWN:
            conds.append(
                sa.or_(lr.c.status.is_(None), lr.c.status == DataStatus.UNKNOWN)
            )
        else:
            conds.append(lr.c.status == f.revenue_status)

    if conds:
        stmt = stmt.where(*conds)

    count_stmt = sa.select(sa.func.count()).select_from(stmt.order_by(None).subquery())

    sort_map = {
        "appid": Game.appid,
        "name": Game.name,
        "release_date": Game.release_date,
        "price": Game.current_price_cents,
        "reviews": ls.c.total_reviews,
        "positive_pct": ls.c.positive_pct,
        "peak_ccu": ls.c.peak_ccu,
        "wishlist": lw.c.wishlist_count,
        "revenue": lr.c.gross_revenue_usd,
    }
    sort_key = f.sort or "-release_date"
    descending = sort_key.startswith("-")
    column = sort_map.get(sort_key.lstrip("-"), Game.release_date)
    order = column.desc().nulls_last() if descending else column.asc().nulls_last()
    stmt = stmt.order_by(order, Game.appid)

    return GamesQuery(stmt=stmt, count_stmt=count_stmt)
