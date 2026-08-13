"""Shared query builder for the games list, dashboard and (Phase 8) exports.

Latest-per-game values come from PostgreSQL DISTINCT ON subqueries.
Wishlist/revenue "latest" prefers confirmed over estimated records, then
the most recent observation — see status_priority() for why that preference
cannot be expressed by ordering on the enum column itself.
"""

from dataclasses import dataclass

import sqlalchemy as sa

from app.models import (
    Camera,
    DataStatus,
    Developer,
    Dimension,
    Festival,
    FollowerSnapshot,
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
    VideoCache,
    WishlistRankEntry,
    WishlistRankSweep,
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


def status_priority(col):
    """Preference order for provenance-carrying records: best status first.

    The data_status enum CANNOT be ordered on directly. `conflicting` was
    appended with ALTER TYPE ADD VALUE (migration 0003), so PostgreSQL sorts
    it *after* `unknown` (confirmed=1, estimated=2, unknown=3, conflicting=4)
    rather than ahead of it. Ordering by the raw column therefore lets a
    stale `unknown` row beat a fresh `conflicting` one — silently, and with
    no error. This CASE fixes the order without rebuilding the enum, which
    would touch five columns across four tables.
    """
    return sa.case(
        (col == DataStatus.CONFIRMED, 0),
        (col == DataStatus.ESTIMATED, 1),
        (col == DataStatus.CONFLICTING, 2),
        else_=3,  # unknown, and NULL, last
    )


def latest_wishlist_sq():
    return (
        sa.select(WishlistRecord)
        .distinct(WishlistRecord.appid)
        .order_by(
            WishlistRecord.appid,
            status_priority(WishlistRecord.status),
            # disclosed_on before recorded_at: a harvest ingests a game's
            # whole milestone history in ONE transaction, so every row shares
            # recorded_at and it cannot break the tie. Ordering on it alone
            # surfaced an arbitrary row -- a game that had announced 50,000
            # displayed its oldest 20,000 milestone.
            WishlistRecord.disclosed_on.desc().nullslast(),
            WishlistRecord.recorded_at.desc(),
        )
        .subquery("latest_wishlist")
    )


def latest_revenue_sq():
    return (
        sa.select(RevenueRecord)
        .distinct(RevenueRecord.appid)
        .order_by(
            RevenueRecord.appid,
            status_priority(RevenueRecord.status),
            RevenueRecord.recorded_at.desc(),
        )
        .subquery("latest_revenue")
    )


FOLLOWER_DELTA_DAYS = 14
RANK_DELTA_DAYS = 7


def latest_followers_sq():
    return (
        sa.select(FollowerSnapshot)
        .distinct(FollowerSnapshot.appid)
        .order_by(FollowerSnapshot.appid, FollowerSnapshot.captured_at.desc())
        .subquery("latest_followers")
    )


def prior_followers_sq(days: int = FOLLOWER_DELTA_DAYS):
    """Newest snapshot AT LEAST `days` old — not "the snapshot from `days`
    ago". Collection cadence drifts, so an exact-date match would return
    NULL for most games most of the time."""
    cutoff = sa.func.now() - sa.text(f"interval '{int(days)} days'")
    return (
        sa.select(FollowerSnapshot)
        .distinct(FollowerSnapshot.appid)
        .where(FollowerSnapshot.captured_at <= cutoff)
        .order_by(FollowerSnapshot.appid, FollowerSnapshot.captured_at.desc())
        .subquery("prior_followers")
    )


def _complete_sweep_entries(max_started_at=None):
    """Entries from the newest COMPLETE sweep (optionally, the newest one at
    least as old as `max_started_at`).

    Partial sweeps are excluded on purpose: a run aborted by rate limiting
    holds only the head of the chart, so differencing against it would read
    as "everything below rank N left the chart" and manufacture enormous
    fake deltas.
    """
    sweeps = sa.select(WishlistRankSweep.id).where(WishlistRankSweep.status == "complete")
    if max_started_at is not None:
        sweeps = sweeps.where(WishlistRankSweep.started_at <= max_started_at)
    sweep_id = sweeps.order_by(WishlistRankSweep.started_at.desc()).limit(1).scalar_subquery()
    return sa.select(WishlistRankEntry).where(WishlistRankEntry.sweep_id == sweep_id)


def latest_rank_sq():
    return _complete_sweep_entries().subquery("latest_rank")


def prior_rank_sq(days: int = RANK_DELTA_DAYS):
    cutoff = sa.func.now() - sa.text(f"interval '{int(days)} days'")
    return _complete_sweep_entries(max_started_at=cutoff).subquery("prior_rank")


def video_counts_sq():
    """Cached community-video count per game (0 rows for never-fetched games)."""
    return (
        sa.select(
            VideoCache.appid,
            sa.func.jsonb_array_length(VideoCache.payload["clips"]).label("video_count"),
        ).subquery("video_counts")
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
    has_website: bool | None = None
    has_videos: bool | None = None
    next_fest: bool | None = None
    release_status: str = "all"  # released | upcoming | all
    early_access: bool | None = None
    free: bool | None = None
    release_month: int | None = None
    min_reviews: int | None = None
    min_positive_pct: float | None = None
    min_peak_ccu: int | None = None
    min_revenue: float | None = None
    min_followers: int | None = None
    # True = only games on Valve's wishlist chart; False = only those off it.
    ranked_only: bool | None = None
    max_wishlist_rank: int | None = None
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
    lf, pf = latest_followers_sq(), prior_followers_sq()
    lrk, prk = latest_rank_sq(), prior_rank_sq()
    nf = next_fest_exists()
    vc = video_counts_sq()
    video_count = sa.func.coalesce(vc.c.video_count, 0)

    # Derived in the SELECT, never stored: both are pure functions of two
    # rows, so materialising them would create a staleness class this schema
    # does not otherwise have.
    follower_delta = lf.c.followers - pf.c.followers
    # Positive = moved UP the chart (rank 40 -> 12 is +28).
    rank_delta = prk.c.rank - lrk.c.rank

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
            lw.c.comparator.label("wishlist_comparator"),
            lw.c.disclosed_on.label("wishlist_disclosed_on"),
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
            # --- first-party measured demand signals -----------------------
            lf.c.followers.label("followers"),
            lf.c.captured_at.label("followers_captured_at"),
            lf.c.source_url.label("followers_source_url"),
            follower_delta.label("follower_delta"),
            (follower_delta * 100.0 / sa.func.nullif(pf.c.followers, 0)).label(
                "follower_delta_pct"
            ),
            lrk.c.rank.label("wishlist_rank"),
            rank_delta.label("rank_delta"),
            video_count.label("video_count"),
        )
        .outerjoin(ls, ls.c.appid == Game.appid)
        .outerjoin(lw, lw.c.appid == Game.appid)
        .outerjoin(lr, lr.c.appid == Game.appid)
        .outerjoin(MarketingInfo, MarketingInfo.appid == Game.appid)
        .outerjoin(lf, lf.c.appid == Game.appid)
        .outerjoin(pf, pf.c.appid == Game.appid)
        # INNER-JOIN semantics would drop every unranked game; the chart is a
        # global ~5.2k list and most of this catalogue is not on it, so these
        # must stay outer joins and "not ranked" must read as NULL.
        .outerjoin(lrk, lrk.c.appid == Game.appid)
        .outerjoin(prk, prk.c.appid == Game.appid)
        .outerjoin(vc, vc.c.appid == Game.appid)
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
    if f.has_website is not None:
        # '' means "checked, none listed"; NULL means never checked — neither counts.
        has_site = sa.and_(Game.website.is_not(None), Game.website != "")
        conds.append(has_site if f.has_website else sa.not_(has_site))
    if f.has_videos is not None:
        conds.append(video_count > 0 if f.has_videos else video_count == 0)
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
    if f.min_revenue is not None:
        conds.append(lr.c.gross_revenue_usd >= f.min_revenue)
    if f.min_followers is not None:
        conds.append(lf.c.followers >= f.min_followers)
    if f.ranked_only is not None:
        conds.append(lrk.c.rank.is_not(None) if f.ranked_only else lrk.c.rank.is_(None))
    if f.max_wishlist_rank is not None:
        conds.append(lrk.c.rank <= f.max_wishlist_rank)
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
        # No `wishlist` or `revenue` sort key. Both columns end up all-NULL:
        # wishlist carries only developer disclosures (mostly ">=" lower
        # bounds, which do not order meaningfully), and migration 0013 deletes
        # every vendor revenue row — the retired SteamSpy rows carried 0
        # revenue values across 8,380 rows anyway.
        "followers": lf.c.followers,
        "follower_delta_14d": follower_delta,
        # NB: ascending is BETTER for rank (1 is the top of the chart), unlike
        # every other key here. Callers wanting "best first" pass "wishlist_rank",
        # not "-wishlist_rank".
        "wishlist_rank": lrk.c.rank,
        "rank_delta_7d": rank_delta,
        "videos": video_count,
    }
    sort_key = f.sort or "-release_date"
    descending = sort_key.startswith("-")
    column = sort_map.get(sort_key.lstrip("-"), Game.release_date)
    order = column.desc().nulls_last() if descending else column.asc().nulls_last()
    stmt = stmt.order_by(order, Game.appid)

    return GamesQuery(stmt=stmt, count_stmt=count_stmt)
