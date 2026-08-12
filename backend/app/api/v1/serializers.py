"""Row → schema converters shared by the games endpoints and exports."""

from app.models import Game
from app.schemas.common import Provenanced
from app.schemas.game import (
    BudgetEstimateOut,
    CompanyOut,
    FestivalOut,
    GameDetail,
    GameListItem,
    MarketingOut,
    MediaOut,
    RevenueEstimateOut,
    RevenueRecordOut,
    StatsPoint,
    TagOut,
    WishlistRecordOut,
)

LIST_TAG_LIMIT = 10


def _enum_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _provenanced(
    value, status, source_name=None, source_url=None, recorded_at=None, spread=None
) -> Provenanced:
    return Provenanced(
        value=float(value) if value is not None else None,
        status=_enum_value(status) if status is not None else "unknown",
        source_name=source_name,
        source_url=source_url,
        recorded_at=recorded_at,
        estimate_spread=float(spread) if spread is not None else None,
    )


def row_to_list_item(row) -> GameListItem:
    """row: Row of (Game, labeled columns...) from build_games_query."""
    game: Game = row.Game
    return GameListItem(
        appid=game.appid,
        name=game.name,
        header_image_url=game.header_image_url,
        capsule_image_url=game.capsule_image_url,
        steam_store_url=game.steam_store_url,
        steamdb_url=game.steamdb_url,
        developers=[d.name for d in game.developers],
        publishers=[p.name for p in game.publishers],
        release_date=game.release_date,
        release_date_raw=game.release_date_raw,
        is_released=game.is_released,
        coming_soon=game.coming_soon,
        early_access=game.early_access,
        demo_available=game.demo_available,
        demo_release_date=game.demo_release_date,
        next_fest=bool(row.next_fest),
        genres=[g.name for g in game.genres],
        tags=[t.name for t in game.tags[:LIST_TAG_LIMIT]],
        dimension=_enum_value(game.dimension),
        camera=_enum_value(game.camera),
        graphics_style=_enum_value(game.graphics_style),
        engine=_enum_value(game.engine),
        indie_confidence=_enum_value(game.indie_confidence),
        low_quality_signal=game.low_quality_signal,
        is_free=game.is_free,
        currency=game.currency,
        current_price_cents=game.current_price_cents,
        total_reviews=row.total_reviews,
        positive_pct=float(row.positive_pct) if row.positive_pct is not None else None,
        review_score_desc=row.review_score_desc,
        peak_ccu=row.peak_ccu,
        avg_ccu=float(row.avg_ccu) if row.avg_ccu is not None else None,
        wishlist=_provenanced(
            row.wishlist_count, row.wishlist_status, row.wishlist_source,
            row.wishlist_source_url, row.wishlist_recorded_at,
        ),
        revenue=_provenanced(
            row.revenue_gross, row.revenue_status, row.revenue_source,
            row.revenue_source_url, row.revenue_recorded_at,
            spread=row.revenue_spread,
        ),
        estimated_sales=row.estimated_sales,
        budget=_provenanced(
            row.budget_value, row.budget_status, row.budget_source, row.budget_source_url,
        ),
    )


def company_out(company) -> CompanyOut:
    return CompanyOut(
        id=company.id,
        name=company.name,
        country=company.country,
        country_status=_enum_value(company.country_status),
        website=company.website,
    )


def stats_point(stats) -> StatsPoint:
    return StatsPoint(
        captured_at=stats.captured_at,
        positive_reviews=stats.positive_reviews,
        negative_reviews=stats.negative_reviews,
        total_reviews=stats.total_reviews,
        positive_pct=float(stats.positive_pct) if stats.positive_pct is not None else None,
        review_score=stats.review_score,
        review_score_desc=stats.review_score_desc,
        peak_ccu=stats.peak_ccu,
        avg_ccu=float(stats.avg_ccu) if stats.avg_ccu is not None else None,
        followers=stats.followers,
        source_name=stats.source_name,
    )


def build_detail(
    base: GameListItem,
    game: Game,
    tag_rows,
    festival_rows,
    latest,
    wishlist_history,
    revenue_history,
    revenue_estimates=(),
    budget_estimates=(),
) -> GameDetail:
    marketing = None
    if game.marketing_info is not None:
        info = game.marketing_info
        marketing = MarketingOut(
            budget=_provenanced(
                info.budget_estimate_usd, info.budget_status, info.source_name, info.source_url
            ),
            marketing_notes=info.marketing_notes,
            developer_interview_url=info.developer_interview_url,
            publisher_interview_url=info.publisher_interview_url,
            kickstarter_url=info.kickstarter_url,
        )

    return GameDetail(
        **base.model_dump(),
        short_description=game.short_description,
        website=game.website or None,  # '' means "checked, none reported"
        discovery_method=game.discovery_method,
        dimension_source=game.dimension_source,
        supported_languages=game.supported_languages or [],
        controller_support=_enum_value(game.controller_support),
        steam_deck_support=_enum_value(game.steam_deck_support),
        launch_price_cents=game.launch_price_cents,
        launch_discount_pct=game.launch_discount_pct,
        page_creation_date=game.page_creation_date,
        page_creation_source=game.page_creation_source,
        demo_appid=game.demo_appid,
        last_synced_at=game.last_synced_at,
        developers_full=[company_out(d) for d in game.developers],
        publishers_full=[company_out(p) for p in game.publishers],
        tags_full=[
            TagOut(name=name, rank=rank, votes=votes) for name, rank, votes in tag_rows
        ],
        media=[
            MediaOut(
                media_type=_enum_value(m.media_type),
                url=m.url,
                thumbnail_url=m.thumbnail_url,
                position=m.position,
            )
            for m in game.media_assets
        ],
        festivals=[
            FestivalOut(
                name=name, is_next_fest=is_nf, start_date=start, end_date=end,
                source_url=src, notes=notes,
            )
            for name, is_nf, start, end, src, notes in festival_rows
        ],
        latest_stats=stats_point(latest) if latest is not None else None,
        wishlist_history=[
            WishlistRecordOut(
                status=_enum_value(w.status),
                wishlist_count=w.wishlist_count,
                source_name=w.source_name,
                source_url=w.source_url,
                recorded_at=w.recorded_at,
                notes=w.notes,
            )
            for w in wishlist_history
        ],
        revenue_history=[
            RevenueRecordOut(
                status=_enum_value(r.status),
                gross_revenue_usd=(
                    float(r.gross_revenue_usd) if r.gross_revenue_usd is not None else None
                ),
                net_revenue_usd=(
                    float(r.net_revenue_usd) if r.net_revenue_usd is not None else None
                ),
                estimated_sales=r.estimated_sales,
                estimated_owners_min=r.estimated_owners_min,
                estimated_owners_max=r.estimated_owners_max,
                estimate_spread=(
                    float(r.estimate_spread) if r.estimate_spread is not None else None
                ),
                source_name=r.source_name,
                source_url=r.source_url,
                recorded_at=r.recorded_at,
                notes=r.notes,
            )
            for r in revenue_history
        ],
        revenue_estimates=[
            RevenueEstimateOut(
                source_name=e.source_name,
                status=_enum_value(e.status),
                revenue_usd=float(e.revenue_usd) if e.revenue_usd is not None else None,
                estimated_sales=e.estimated_sales,
                owners_min=e.owners_min,
                owners_max=e.owners_max,
                wishlist_count=e.wishlist_count,
                source_url=e.source_url,
                retrieved_at=e.retrieved_at,
            )
            for e in revenue_estimates
        ],
        budget_estimates=[
            BudgetEstimateOut(
                method=b.method,
                budget_min_usd=float(b.budget_min_usd) if b.budget_min_usd is not None else None,
                budget_max_usd=float(b.budget_max_usd) if b.budget_max_usd is not None else None,
                formula=b.formula,
                inputs=b.inputs,
                source_name=b.source_name,
                source_url=b.source_url,
                computed_at=b.computed_at,
            )
            for b in budget_estimates
        ],
        marketing=marketing,
    )
