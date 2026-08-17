from collections import defaultdict
import itertools
from collections.abc import Sequence
from typing import NamedTuple

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models import (
    DataStatus,
    Dimension,
    Game,
    Genre,
    RevenueEstimate,
    RevenueRecord,
    game_genres,
)
from app.schemas.charts import (
    BreakdownPoint,
    ClassificationRow,
    ClassificationSummaryOut,
    ChartsOut,
    GenreBands,
    GenreRevenueDistributionOut,
    GenreRevenueSlice,
    GenreRevenueBand,
    GenreTierBreakdownOut,
    GenreSuccessOut,
    GenreSuccessOverviewOut,
    GenreSuccessSlice,
    MonthPoint,
    RevenueMethodOut,
    SuccessBandPoint,
)
from app.schemas.game import AverageStat, DashboardSummary
from app.services import classification, revenue_estimate, success_bands
from app.services.games_query import (
    latest_followers_sq,
    latest_rank_sq,
    latest_stats_sq,
    latest_wishlist_sq,
    next_fest_exists,
)

router = APIRouter()


async def _count(db: AsyncSession, *conds) -> int:
    stmt = sa.select(sa.func.count()).select_from(Game)
    if conds:
        stmt = stmt.where(*conds)
    return (await db.execute(stmt)).scalar_one()


async def _avg(db: AsyncSession, sq_column) -> AverageStat:
    """Average over rows that actually have the value — no invented zeros."""
    stmt = sa.select(
        sa.func.avg(sq_column), sa.func.count(sq_column)
    ).where(sq_column.is_not(None))
    value, count = (await db.execute(stmt)).one()
    return AverageStat(
        value=round(float(value), 2) if value is not None else None,
        sample_size=count,
    )


async def _count_matching(db: AsyncSession, sq, extra=None) -> int:
    """Catalogue games having a row in `sq`. Inner join, so chart entries for
    games outside this catalogue are excluded."""
    stmt = (
        sa.select(sa.func.count())
        .select_from(Game)
        .join(sq, sq.c.appid == Game.appid)
    )
    if extra is not None:
        stmt = stmt.where(extra)
    return (await db.execute(stmt)).scalar_one()


@router.get("/summary", response_model=DashboardSummary)
async def summary(db: AsyncSession = Depends(get_db)) -> DashboardSummary:
    ls, lw = latest_stats_sq(), latest_wishlist_sq()
    lf, lrk = latest_followers_sq(), latest_rank_sq()
    return DashboardSummary(
        total_games=await _count(db),
        released_games=await _count(db, Game.is_released.is_(True)),
        coming_soon_games=await _count(db, Game.coming_soon.is_(True)),
        two_d_games=await _count(db, Game.dimension == Dimension.TWO_D),
        three_d_games=await _count(db, Game.dimension == Dimension.THREE_D),
        games_with_demo=await _count(db, Game.demo_available.is_(True)),
        next_fest_games=await _count(db, next_fest_exists()),
        avg_reviews=await _avg(db, ls.c.total_reviews),
        # Coverage counters rather than averages. An average wishlist figure
        # would be computed over a handful of developer disclosures that are
        # mostly lower bounds — a number with no defensible meaning.
        games_with_followers=await _count_matching(db, lf),
        ranked_games=await _count_matching(db, lrk),
        confirmed_wishlist_games=await _count_matching(
            db, lw, lw.c.status == DataStatus.CONFIRMED
        ),
    )


async def _breakdown(db: AsyncSession, column) -> list[BreakdownPoint]:
    rows = await db.execute(
        sa.select(column, sa.func.count())
        .select_from(Game)
        .group_by(column)
        .order_by(sa.func.count().desc())
    )
    return [
        BreakdownPoint(
            key=value.value if hasattr(value, "value") else str(value), count=count
        )
        for value, count in rows
    ]


@router.get("/charts", response_model=ChartsOut)
async def charts(db: AsyncSession = Depends(get_db)) -> ChartsOut:
    month = sa.extract("month", Game.release_date)
    month_rows = await db.execute(
        sa.select(
            month.label("m"),
            sa.func.count().filter(Game.is_released.is_(True)),
            sa.func.count().filter(Game.is_released.is_(False)),
        )
        .where(Game.release_date.is_not(None))
        .group_by(month)
        .order_by(month)
    )
    releases_by_month = [
        MonthPoint(month=int(m), released=released, upcoming=upcoming)
        for m, released, upcoming in month_rows
    ]

    genre_rows = await db.execute(
        sa.select(Genre.name, sa.func.count(game_genres.c.appid))
        .join(game_genres, game_genres.c.genre_id == Genre.id)
        # Every cataloged game is Indie by construction — showing it says nothing.
        .where(Genre.name != "Indie")
        .group_by(Genre.id, Genre.name)
        .order_by(sa.func.count(game_genres.c.appid).desc())
        .limit(10)
    )
    top_genres = [BreakdownPoint(key=name, count=count) for name, count in genre_rows]

    return ChartsOut(
        releases_by_month=releases_by_month,
        by_dimension=await _breakdown(db, Game.dimension),
        by_engine=await _breakdown(db, Game.engine),
        by_graphics_style=await _breakdown(db, Game.graphics_style),
        top_genres=top_genres,
    )


def _ranked_games_sq():
    """Every rankable game with its percentile position among its own cohort.

    Rankable means released, dated and carrying a review count — the three
    things the ranking needs. percent_rank() runs per release month so a game
    competes with releases that have had the same time to accumulate reviews;
    see app.services.success_bands for why that matters.
    """
    ls = latest_stats_sq()
    cohort = sa.func.date_trunc("month", Game.release_date)
    return (
        sa.select(
            Game.appid.label("appid"),
            sa.func.percent_rank()
            .over(partition_by=cohort, order_by=ls.c.total_reviews)
            .label("pr"),
        )
        .select_from(Game)
        .join(ls, ls.c.appid == Game.appid)
        .where(
            Game.is_released.is_(True),
            Game.release_date.is_not(None),
            ls.c.total_reviews.is_not(None),
            ls.c.total_reviews > 0,
        )
        .subquery("ranked")
    )


def _band_case(pr_column):
    """percent_rank → band key, in SQL so the counting stays one query."""
    return sa.case(
        *[
            (pr_column >= band.min_percentile, band.key)
            for band in success_bands.SUCCESS_BANDS
        ],
        else_=success_bands.SUCCESS_BANDS[-1].key,
    )


@router.get("/classification-summary", response_model=ClassificationSummaryOut)
async def classification_summary(
    db: AsyncSession = Depends(get_db),
) -> ClassificationSummaryOut:
    """The whole catalogue split across the effort × traction quadrants.

    Split further by Game.is_released — the same flag the release_status
    filter and the releases-by-month chart use, so a row's released count
    equals what `?classification=…&release_status=released` returns.
    """
    rows = await db.execute(
        sa.select(
            Game.classification,
            Game.classification_confidence,
            Game.is_released,
            sa.func.count(),
        ).group_by(Game.classification, Game.classification_confidence, Game.is_released)
    )
    counts: dict[str, int] = defaultdict(int)
    released: dict[str, int] = defaultdict(int)
    upcoming: dict[str, int] = defaultdict(int)
    by_confidence: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for label, confidence, is_released, count in rows:
        counts[label] += count
        (released if is_released else upcoming)[label] += count
        by_confidence[label][confidence] += count
    total = sum(counts.values())
    released_total = sum(released.values())
    upcoming_total = sum(upcoming.values())

    return ClassificationSummaryOut(
        total=total,
        released_total=released_total,
        upcoming_total=upcoming_total,
        rows=[
            ClassificationRow(
                label=label,
                count=count,
                share=round(count / total, 4) if total else 0.0,
                released_count=released[label],
                upcoming_count=upcoming[label],
                total_count=count,
                # Shares within each subtotal, so the two columns can be read
                # as distributions in their own right and not only against
                # the catalogue as a whole.
                released_share=(
                    round(released[label] / released_total, 4) if released_total else 0.0
                ),
                upcoming_share=(
                    round(upcoming[label] / upcoming_total, 4) if upcoming_total else 0.0
                ),
                highlight=label == classification.HIGH_EFFORT_LOW_TRACTION,
                by_confidence=dict(sorted(by_confidence[label].items())),
            )
            # Biggest first, so the table reads as a distribution; the
            # highlight flag keeps the overlooked group findable regardless.
            for label, count in sorted(counts.items(), key=lambda kv: -kv[1])
        ],
    )


@router.get("/genre-success-overview", response_model=GenreSuccessOverviewOut)
async def genre_success_overview(
    limit: int = Query(10, ge=1, le=25, description="how many genres, by catalogue size"),
    db: AsyncSession = Depends(get_db),
) -> GenreSuccessOverviewOut:
    """Every top genre's standing in one response.

    Same ranking as /genre-success, computed once and grouped by genre so the
    genres can be compared against each other rather than one at a time.
    """
    ranked = _ranked_games_sq()
    band_key = _band_case(ranked.c.pr)

    top_genres = (
        sa.select(Genre.id)
        .join(game_genres, game_genres.c.genre_id == Genre.id)
        # Every catalogued game is Indie by construction — it says nothing.
        .where(Genre.name != "Indie")
        .group_by(Genre.id)
        .order_by(sa.func.count(game_genres.c.appid).desc())
        .limit(limit)
        .subquery("top_genres")
    )
    rows = await db.execute(
        sa.select(Genre.name, band_key.label("band"), sa.func.count())
        .select_from(Game)
        .join(ranked, ranked.c.appid == Game.appid)
        .join(game_genres, game_genres.c.appid == Game.appid)
        .join(Genre, Genre.id == game_genres.c.genre_id)
        .join(top_genres, top_genres.c.id == Genre.id)
        .group_by(Genre.name, band_key)
    )

    counts: dict[str, dict[str, int]] = {}
    for genre_name, band, count in rows:
        counts.setdefault(genre_name, {})[band] = count

    genres = []
    for genre_name, per_band in counts.items():
        scored = sum(per_band.values())
        genres.append(
            GenreBands(
                genre=genre_name,
                games_scored=scored,
                bands=[
                    SuccessBandPoint(
                        key=band.key,
                        label=band.label,
                        count=per_band.get(band.key, 0),
                        share=round(per_band.get(band.key, 0) / scored, 4) if scored else 0.0,
                        baseline_share=success_bands.BASELINE_SHARE[band.key],
                        min_percentile=band.min_percentile,
                    )
                    for band in success_bands.SUCCESS_BANDS
                ],
            )
        )
    # Best-standing genre first: the ordering people actually want to read.
    genres.sort(
        key=lambda g: next(b.share for b in g.bands if b.key == "top_10"), reverse=True
    )

    # --- who the top-decile games are, by primary genre ---------------------
    # A game carries several genres, so counting it under each would make the
    # slices sum well past 100%. Steam's own genre order is stored as
    # game_genres.rank, so the lowest-ranked genre that is not "Indie" (which
    # every game here carries) is the primary one.
    primary = (
        sa.select(
            game_genres.c.appid,
            sa.func.min(game_genres.c.rank).label("rank"),
        )
        .join(Genre, Genre.id == game_genres.c.genre_id)
        .where(Genre.name != "Indie")
        .group_by(game_genres.c.appid)
        .subquery("primary_rank")
    )
    top_bar = success_bands.SUCCESS_BANDS[1].min_percentile
    # Both counts live in the same universe — games grouped by primary genre —
    # so the slice and the rate divide comparable things. Mixing a primary-genre
    # numerator with an any-genre denominator produced rates that contradicted
    # the per-genre view (an RPG usually lists Action or Adventure first).
    rows_by_primary = await db.execute(
        sa.select(
            Genre.name,
            sa.func.count(),
            sa.func.count().filter(ranked.c.pr >= top_bar),
        )
        .select_from(ranked)
        .join(primary, primary.c.appid == ranked.c.appid)
        .join(
            game_genres,
            sa.and_(
                game_genres.c.appid == ranked.c.appid,
                game_genres.c.rank == primary.c.rank,
            ),
        )
        .join(Genre, Genre.id == game_genres.c.genre_id)
        .group_by(Genre.name)
    )
    by_primary = [(name, scored, top) for name, scored, top in rows_by_primary.all()]
    total_top = sum(top for _, _, top in by_primary)
    baseline_rate = success_bands.BASELINE_SHARE["top_10"]

    composition = [
        GenreSuccessSlice(
            genre=name,
            count=top,
            share=round(top / total_top, 4) if total_top else 0.0,
            scored=scored,
            rate=round(top / scored, 4) if scored else 0.0,
            over_index=round((top / scored) / baseline_rate, 2) if scored else 0.0,
        )
        for name, scored, top in by_primary
        if top > 0
    ]
    composition.sort(key=lambda s: s.count, reverse=True)

    return GenreSuccessOverviewOut(
        measure=success_bands.MEASURE,
        cohort=success_bands.COHORT,
        method=success_bands.METHOD_NAME,
        notes=success_bands.NOTES,
        genres=genres,
        composition=composition,
        top_band_label=success_bands.SUCCESS_BANDS[1].label,
    )


@router.get("/genre-success", response_model=GenreSuccessOut)
async def genre_success(
    genre: str = Query(..., min_length=1, description="Genre name, case-insensitive"),
    db: AsyncSession = Depends(get_db),
) -> GenreSuccessOut:
    """Where a genre's games sit among their release-month peers.

    Ranks Steam's own review counts — nothing is estimated, so there is no
    multiplier to argue with. Games that cannot be ranked (unreleased, or no
    reviews yet) are counted separately rather than dropped into a band.
    """
    in_genre = (
        sa.select(game_genres.c.appid)
        .join(Genre, Genre.id == game_genres.c.genre_id)
        .where(
            game_genres.c.appid == Game.appid,
            sa.func.lower(Genre.name) == genre.strip().lower(),
        )
        .exists()
    )
    games_in_genre = await _count(db, in_genre)
    if not games_in_genre:
        raise HTTPException(status_code=404, detail=f"No games found for genre '{genre}'")

    ranked = _ranked_games_sq()
    band_key = _band_case(ranked.c.pr)
    rows = await db.execute(
        sa.select(band_key.label("band"), sa.func.count())
        .select_from(Game)
        .join(ranked, ranked.c.appid == Game.appid)
        .where(in_genre)
        .group_by(band_key)
    )
    counts = {band: count for band, count in rows}
    scored = sum(counts.values())

    unreleased = await _count(db, in_genre, Game.is_released.is_(False))
    return GenreSuccessOut(
        genre=genre.strip(),
        games_in_genre=games_in_genre,
        games_scored=scored,
        games_excluded_unreleased=unreleased,
        # Whatever is left: released but no review count yet (or no release date).
        games_excluded_no_reviews=games_in_genre - unreleased - scored,
        measure=success_bands.MEASURE,
        cohort=success_bands.COHORT,
        method=success_bands.METHOD_NAME,
        notes=success_bands.NOTES,
        bands=[
            SuccessBandPoint(
                key=band.key,
                label=band.label,
                count=counts.get(band.key, 0),
                share=round(counts.get(band.key, 0) / scored, 4) if scored else 0.0,
                baseline_share=success_bands.BASELINE_SHARE[band.key],
                min_percentile=band.min_percentile,
            )
            for band in success_bands.SUCCESS_BANDS
        ],
    )


# The thresholds the UI offers, in one place so the buttons and the query
# cannot drift apart. Net revenue, i.e. what reaches the developer.
REVENUE_TIERS: tuple[tuple[str, float], ...] = (
    ("All", 0.0),
    ("$10K+", 10_000.0),
    ("$50K+", 50_000.0),
    ("$100K+", 100_000.0),
    ("$500K+", 500_000.0),
    ("$1M+", 1_000_000.0),
)

# Slices thinner than this are folded into "Other" — a pie with forty
# one-percent wedges communicates nothing.
OTHER_SLICE_BELOW = 0.02
OTHER_LABEL = "Other"


class _Band(NamedTuple):
    label: str
    min_revenue: float
    max_revenue: float | None


# The same boundaries as REVENUE_TIERS, read as intervals instead of floors.
# Kept adjacent to it so the two can never drift: the per-genre pie's bands
# and the all-genres pie's thresholds have to describe the same money.
REVENUE_BANDS: tuple[_Band, ...] = (
    _Band("Under $10K", 0.0, 10_000.0),
    _Band("$10K–$50K", 10_000.0, 50_000.0),
    _Band("$50K–$100K", 50_000.0, 100_000.0),
    _Band("$100K–$500K", 100_000.0, 500_000.0),
    _Band("$500K–$1M", 500_000.0, 1_000_000.0),
    _Band("$1M+", 1_000_000.0, None),
)


# A band set is fully described by its ascending floors: consecutive pairs
# become the closed bands and the last floor opens the top one. Callers send
# floors rather than labelled intervals so a malformed set — overlapping,
# unordered, gapped — cannot be expressed in the first place.
MAX_BANDS = 10


def _money_label(value: float) -> str:
    """$500, $10K, $1.5M — the shortest form that stays exact."""
    if value >= 1_000_000:
        scaled, suffix = value / 1_000_000, "M"
    elif value >= 1_000:
        scaled, suffix = value / 1_000, "K"
    else:
        return f"${value:,.0f}"
    text = f"{scaled:.1f}".rstrip("0").rstrip(".")
    return f"${text}{suffix}"


def bands_from_floors(floors: Sequence[float]) -> tuple[_Band, ...]:
    """Ascending floors -> labelled bands, labelling them the way a reader
    would: 'Under $10K' for the first, '$1M+' for the last, ranges between."""
    bands: list[_Band] = []
    for index, floor in enumerate(floors):
        ceiling = floors[index + 1] if index + 1 < len(floors) else None
        if ceiling is None:
            label = f"{_money_label(floor)}+"
        elif index == 0 and floor == 0:
            label = f"Under {_money_label(ceiling)}"
        else:
            label = f"{_money_label(floor)}–{_money_label(ceiling)}"
        bands.append(_Band(label, floor, ceiling))
    return tuple(bands)


def parse_band_floors(raw: str | None) -> tuple[_Band, ...]:
    """Turn a `floors=0,10000,1000000` parameter into bands.

    Rejects rather than repairs: a silently reordered or de-duplicated set
    would draw a chart the caller did not ask for and could not tell apart
    from the one they did.
    """
    if not raw or not raw.strip():
        return REVENUE_BANDS
    try:
        floors = [float(part) for part in raw.split(",") if part.strip()]
    except ValueError:
        raise HTTPException(422, "floors must be numbers separated by commas") from None
    if len(floors) < 2:
        raise HTTPException(422, "give at least two floors — one band cannot be a pie")
    if len(floors) > MAX_BANDS:
        raise HTTPException(422, f"at most {MAX_BANDS} bands")
    if floors[0] != 0:
        raise HTTPException(422, "the first floor must be 0, or games below it vanish")
    if any(b <= a for a, b in itertools.pairwise(floors)):
        raise HTTPException(422, "floors must ascend and not repeat")
    return bands_from_floors(floors)


def _tier_label(min_revenue: float) -> str:
    """The closest configured label, so an arbitrary threshold still names itself."""
    for label, floor in reversed(REVENUE_TIERS):
        if min_revenue >= floor:
            return label if floor == min_revenue else f"${min_revenue:,.0f}+"
    return "All"


def _estimable_revenue_sq():
    """One row per game with a usable net-revenue estimate, latest first.

    revenue_records is append-only, so DISTINCT ON keeps the current summary
    and drops superseded ones.
    """
    return (
        sa.select(RevenueRecord.appid, RevenueRecord.net_revenue_usd)
        .distinct(RevenueRecord.appid)
        .where(RevenueRecord.net_revenue_usd.is_not(None))
        .order_by(RevenueRecord.appid, RevenueRecord.recorded_at.desc())
        .subquery("revenue")
    )


def _above_sq(revenue, min_revenue: float, name: str = "above"):
    return (
        sa.select(revenue.c.appid, revenue.c.net_revenue_usd)
        .where(revenue.c.net_revenue_usd >= min_revenue)
        .subquery(name)
    )


def _method_out() -> RevenueMethodOut:
    """The arithmetic, read straight off the estimator's own constants.

    Shipped with every response so the UI never keeps a second copy of a
    number that can change.
    """
    return RevenueMethodOut(
        formula=(
            "copies solves U = reviews x multiplier(U), x early_access_factor; "
            "net = copies x list_price x asp x steam_share x refunds x regional"
        ),
        constants={
            "asp": revenue_estimate.ASP_FACTOR,
            "steam_share": revenue_estimate.STEAM_SHARE,
            "refunds": revenue_estimate.REFUND_FACTOR,
            "regional": revenue_estimate.REGIONAL_FACTOR,
            "net_of_gross": round(revenue_estimate.NET_OF_GROSS, 4),
            "early_access": revenue_estimate.EARLY_ACCESS_FACTOR,
        },
        calibration_factor=revenue_estimate.CALIBRATION_FACTOR,
        calibration_sample=revenue_estimate.CALIBRATION_SAMPLE,
        min_reviews=revenue_estimate.MIN_REVIEWS,
    )


ALL_GAMES_LABEL = "All games"


async def _genre_tier_breakdown(
    db: AsyncSession, genre: str | None, bands_def: tuple[_Band, ...] = REVENUE_BANDS
) -> GenreTierBreakdownOut:
    """One genre split into mutually exclusive revenue bands — or, with
    `genre=None`, the whole estimable catalogue split the same way.

    The all-games shape is the baseline a genre is read against: "46% of RPGs
    clear $10K" means little without knowing the catalogue figure it beats.
    It is the same query minus the genre join, so it shares this function
    rather than growing a near-duplicate.

    Exclusive rather than cumulative because these are pie slices: cumulative
    pass-rates are nested ($100K+ games are also $10K+ games) and would sum
    past 100%. The cumulative figure is still reported per band, because that
    is the number two genres can be compared on — "46% of RPGs clear $10K vs
    26% of Casual games" — and the exclusive split alone cannot say it.

    One pass over the genre's rows: a CASE assigns each game its band, so
    six bands cost one query rather than six.
    """
    revenue = _estimable_revenue_sq()
    net = revenue.c.net_revenue_usd

    # RELEASED games are the population, joined to their estimate rather than
    # selected from it. An unreleased game has sold nothing, so it belongs in
    # no revenue band; a released one without an estimate still exists and
    # still earned something, and dropping it was what made the picture wrong.
    band_index = sa.case(
        # Free-to-play: excluded from the bands entirely, counted separately.
        # Their revenue is in items this project does not observe, so "under
        # $10K" would be an assertion about them rather than a missing value.
        (Game.is_free.is_(True), -1),
        # No estimate, paid: the review floor put it here. Fewer than ten
        # public reviews is a few hundred copies at the outside, so the bottom
        # band is right even though the figure is not computed.
        (net.is_(None), 0),
        *[
            (net < bands_def[i].max_revenue, i)
            for i in range(len(bands_def) - 1)
        ],
        else_=len(bands_def) - 1,
    )

    stmt = (
        sa.select(
            band_index.label("band"),
            sa.func.count(),
            sa.func.coalesce(sa.func.sum(net), 0),
            sa.func.count(net).label("estimated"),
        )
        .select_from(Game)
        .outerjoin(revenue, revenue.c.appid == Game.appid)
        .where(Game.is_released.is_(True))
    )
    if genre is not None:
        stmt = (
            stmt.join(game_genres, game_genres.c.appid == Game.appid)
            .join(Genre, Genre.id == game_genres.c.genre_id)
            .where(Genre.name == genre)
        )
    rows = await db.execute(stmt.group_by(band_index))
    counts: dict[int, tuple[int, float, int]] = {
        int(index): (int(count), float(total), int(estimated))
        for index, count, total, estimated in rows
    }

    free_not_estimated = counts.pop(-1, (0, 0.0, 0))[0]
    total_games = sum(count for count, _, _ in counts.values())
    estimated_games = sum(estimated for _, _, estimated in counts.values())
    bottom_count, _, bottom_estimated = counts.get(0, (0, 0.0, 0))
    unestimated_in_bottom = bottom_count - bottom_estimated

    # How many games carry this genre at all, released or not — the
    # denominator behind "3,266 of 10,352 Casual games". For the whole
    # catalogue that is simply the catalogue.
    genre_total = (
        await _count(db)
        if genre is None
        else (
            await db.execute(
                sa.select(sa.func.count())
                .select_from(game_genres)
                .join(Genre, Genre.id == game_genres.c.genre_id)
                .where(Genre.name == genre)
            )
        ).scalar_one()
    )

    bands: list[GenreRevenueBand] = []
    for index, band in enumerate(bands_def):
        count, revenue_sum, _ = counts.get(index, (0, 0.0, 0))
        # Everything in this band or any band above it — the comparable number.
        cumulative = sum(
            counts.get(i, (0, 0.0, 0))[0] for i in range(index, len(bands_def))
        )
        bands.append(
            GenreRevenueBand(
                label=band.label,
                min_revenue=band.min_revenue,
                max_revenue=band.max_revenue,
                game_count=count,
                pct=round(count / total_games, 4) if total_games else 0.0,
                cumulative_count=cumulative,
                cumulative_pct=round(cumulative / total_games, 4) if total_games else 0.0,
                total_revenue_mid=round(revenue_sum, 2),
            )
        )

    return GenreTierBreakdownOut(
        genre=genre if genre is not None else ALL_GAMES_LABEL,
        total_games=total_games,
        estimated_games=estimated_games,
        unestimated_in_bottom=unestimated_in_bottom,
        free_not_estimated=free_not_estimated,
        genre_total=genre_total,
        catalogue_total=await _count(db),
        method=_method_out(),
        bands=bands,
    )


@router.get(
    "/genre-revenue-distribution",
    response_model=GenreRevenueDistributionOut | GenreTierBreakdownOut,
)
async def genre_revenue_distribution(
    min_revenue: float = Query(
        0.0, ge=0, description="net revenue floor in USD; 0 = every estimable game"
    ),
    genre: str | None = Query(
        None,
        description=(
            "when given, returns that genre measured at every tier instead of "
            "the genre mix at one tier; min_revenue is ignored"
        ),
    ),
    floors: str | None = Query(
        None,
        description=(
            "custom band edges as ascending comma-separated USD floors, e.g. "
            "'0,25000,250000'. The first must be 0 and the last opens the top "
            f"band. Up to {MAX_BANDS}. Omit for the default six."
        ),
    ),
    bands: bool = Query(
        False,
        description=(
            "return the whole estimable catalogue split into revenue bands — "
            "the baseline a single genre's bands are read against. Ignored "
            "when `genre` is given, and ignores min_revenue like `genre` does."
        ),
    ),
    db: AsyncSession = Depends(get_db),
) -> GenreRevenueDistributionOut | GenreTierBreakdownOut:
    """Which genres the games above a revenue threshold belong to.

    Estimated net revenue, never a measured one — see
    app.services.revenue_estimate for how it is derived and how wrong it can
    be. The response carries the formula and its constants so the reader is
    not asked to take the number on faith.

    With `genre`, the question flips: one genre, every threshold. The two
    shapes answer different questions and share a route because they share a
    card in the UI.
    """
    if genre and genre.strip():
        return await _genre_tier_breakdown(db, genre.strip(), parse_band_floors(floors))
    if bands:
        return await _genre_tier_breakdown(db, None, parse_band_floors(floors))

    revenue = _estimable_revenue_sq()
    above = _above_sq(revenue, min_revenue)

    totals = (
        await db.execute(
            sa.select(sa.func.count(), sa.func.coalesce(sa.func.sum(above.c.net_revenue_usd), 0))
        )
    ).one()
    game_count, total_revenue = int(totals[0]), float(totals[1])
    estimable_total = (
        await db.execute(sa.select(sa.func.count()).select_from(revenue))
    ).scalar_one()
    catalogue_total = await _count(db)

    rows = await db.execute(
        sa.select(Genre.name, sa.func.count())
        .select_from(above)
        .join(game_genres, game_genres.c.appid == above.c.appid)
        .join(Genre, Genre.id == game_genres.c.genre_id)
        # Every catalogued game is Indie by construction — the slice would
        # be the whole pie and would say nothing.
        .where(Genre.name != "Indie")
        .group_by(Genre.name)
        .order_by(sa.func.count().desc())
    )
    counts = [(name, count) for name, count in rows]
    tag_total = sum(count for _, count in counts)

    slices: list[GenreRevenueSlice] = []
    other = 0
    for name, count in counts:
        pct = count / tag_total if tag_total else 0.0
        if pct < OTHER_SLICE_BELOW:
            other += count
        else:
            slices.append(GenreRevenueSlice(genre=name, count=count, pct=round(pct, 4)))
    if other:
        slices.append(
            GenreRevenueSlice(
                genre=OTHER_LABEL, count=other, pct=round(other / tag_total, 4)
            )
        )

    # Which signals stand behind this tier's games, and how much they disagree.
    signal_rows = await db.execute(
        sa.select(RevenueEstimate.source_name, sa.func.count(sa.distinct(RevenueEstimate.appid)))
        .join(above, above.c.appid == RevenueEstimate.appid)
        .group_by(RevenueEstimate.source_name)
    )
    spread = (
        await db.execute(
            sa.select(
                sa.func.percentile_cont(0.5).within_group(RevenueRecord.estimate_spread)
            ).join(above, above.c.appid == RevenueRecord.appid)
        )
    ).scalar_one()

    return GenreRevenueDistributionOut(
        tier=_tier_label(min_revenue),
        min_revenue=min_revenue,
        game_count=game_count,
        total_revenue_mid=round(total_revenue, 2),
        estimable_total=estimable_total,
        catalogue_total=catalogue_total,
        share_of_estimable=(
            round(game_count / estimable_total, 4) if estimable_total else 0.0
        ),
        share_of_catalogue=round(game_count / catalogue_total, 4) if catalogue_total else 0.0,
        sources_used={name: count for name, count in signal_rows},
        median_spread=round(float(spread), 4) if spread is not None else None,
        method=_method_out(),
        genres=slices,
    )
