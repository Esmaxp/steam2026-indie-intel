"""Market aggregates for the Game Market Analyzer agent.

The agent reading this asks commercial questions — what is breaking out, which
design space is crowded, what correlates with doing well — and turns the
answers into game concepts. That consumer shapes two decisions here.

**Every number is measured or absent.** Steam publishes no wishlist or sales
figures, so this module derives none. Outcomes are expressed as review counts
and as a game's POSITION among its release-month peers, which is invariant to
whatever the true reviews-to-sales multiplier happens to be. An agent cannot
launder an estimate it was never given.

**Every response carries its own coverage.** A momentum signal needs two
observations separated by time, and this catalogue's follower time series is
days old — so "no game is trending" and "the signal does not exist yet" are
both plausible readings of an empty list, and only one of them is true. Each
aggregate reports how many games in scope actually carried the signal it used,
so the agent can tell those apart instead of inferring a quiet market.
"""

import math

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DataStatus,
    Game,
    Genre,
    Tag,
    WishlistRecord,
    game_genres,
    game_tags,
)
from app.services import success_bands
from app.services.games_query import (
    latest_followers_sq,
    latest_rank_sq,
    latest_stats_sq,
    prior_followers_sq,
    prior_rank_sq,
)

# A game needs this many peers in its release month before a percentile
# position means anything. Mirrors success_bands.MIN_COHORT_SIZE.
MIN_COHORT_SIZE = success_bands.MIN_COHORT_SIZE
# Facets thinner than this are reported but flagged: a tag with four games can
# show a 50% top-decile share and mean nothing at all.
MIN_FACET_SAMPLE = 20
# Price buckets in cents, for "what do games in this space charge".
PRICE_BANDS = [
    ("free", 0, 0),
    ("under_5", 1, 499),
    ("5_to_10", 500, 999),
    ("10_to_20", 1000, 1999),
    ("20_to_30", 2000, 2999),
    ("over_30", 3000, None),
]


def cohort_percentile_sq():
    """Each game's percentile position among its own release-month cohort.

    Copied in spirit from dashboard._ranked_games_sq: released, dated, and
    carrying reviews are the three things the ranking needs. Kept here so the
    market endpoints do not import from an API module.
    """
    ls = latest_stats_sq()
    cohort = sa.func.date_trunc("month", Game.release_date)
    return (
        sa.select(
            Game.appid.label("appid"),
            ls.c.total_reviews.label("total_reviews"),
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
        .subquery("cohort_pr")
    )


def _median(column):
    return sa.func.percentile_cont(0.5).within_group(column.asc())


def _p90(column):
    return sa.func.percentile_cont(0.9).within_group(column.asc())


async def coverage(db: AsyncSession) -> dict:
    """What signals actually exist right now, catalogue-wide.

    The agent's first call should be this or the manifest: it decides whether
    a thin momentum list means a quiet market or a young time series.
    """
    ls, lf, lr = latest_stats_sq(), latest_followers_sq(), latest_rank_sq()
    pf, pr = prior_followers_sq(), prior_rank_sq()

    async def count_of(sq, *where):
        stmt = sa.select(sa.func.count()).select_from(Game).join(sq, sq.c.appid == Game.appid)
        return (await db.execute(stmt.where(*where) if where else stmt)).scalar_one()

    total = (await db.execute(sa.select(sa.func.count()).select_from(Game))).scalar_one()
    released = (
        await db.execute(
            sa.select(sa.func.count()).select_from(Game).where(Game.is_released.is_(True))
        )
    ).scalar_one()
    disclosures = (
        await db.execute(
            sa.select(sa.func.count(sa.distinct(WishlistRecord.appid))).where(
                WishlistRecord.status == DataStatus.CONFIRMED
            )
        )
    ).scalar_one()

    with_follower_delta = await count_of(pf)
    with_rank_delta = await count_of(pr)
    return {
        "games": total,
        "released_games": released,
        "with_reviews": await count_of(ls, ls.c.total_reviews.is_not(None)),
        "with_followers": await count_of(lf),
        "with_follower_delta": with_follower_delta,
        "on_wishlist_chart": await count_of(lr),
        "with_rank_delta": with_rank_delta,
        "with_confirmed_wishlist_disclosure": disclosures,
        "momentum_ready": with_follower_delta > 0 or with_rank_delta > 0,
        "notes": _coverage_notes(with_follower_delta, with_rank_delta),
    }


DENSE_SIGNAL_NOTE = (
    "Review counts are Steam's own and cover nearly the whole catalogue — they are "
    "the dense signal here."
)


def _coverage_notes(follower_delta: int, rank_delta: int) -> list[str]:
    notes = [DENSE_SIGNAL_NOTE]
    if not follower_delta:
        notes.append(
            "No game yet has two follower snapshots far enough apart for a 14-day "
            "delta. An empty trending list means the time series is too young, "
            "NOT that demand is flat."
        )
    if not rank_delta:
        notes.append(
            "No complete Top-Wishlists sweep is 7 days old yet, so rank movement "
            "is unavailable. Current rank is still a usable point-in-time signal."
        )
    return notes


def _scope(release_status: str | None, genre: str | None, tag: str | None):
    """Shared WHERE terms for a slice of the catalogue."""
    conds = []
    if release_status == "released":
        conds.append(Game.is_released.is_(True))
    elif release_status == "upcoming":
        conds.append(Game.is_released.is_(False))
    if genre:
        conds.append(
            sa.select(game_genres.c.appid)
            .join(Genre, Genre.id == game_genres.c.genre_id)
            .where(
                game_genres.c.appid == Game.appid,
                sa.func.lower(Genre.name) == genre.strip().lower(),
            )
            .exists()
        )
    if tag:
        conds.append(
            sa.select(game_tags.c.appid)
            .join(Tag, Tag.id == game_tags.c.tag_id)
            .where(
                game_tags.c.appid == Game.appid,
                sa.func.lower(Tag.name) == tag.strip().lower(),
            )
            .exists()
        )
    return conds


# --- Trending -------------------------------------------------------------
#
# Released and upcoming games are ranked by different algorithms because they
# emit different signals. A released game has reviews; an unreleased one has
# none by definition, and its only first-party demand signals are Valve's
# Top-Wishlists position and community-hub followers.
#
# The previous single ranking added follower_delta to rank_delta, which summed
# people and chart positions as though they were the same unit.

# Wilson score interval, 95% (z = 1.96). Turns "how positive" into "how
# positive, discounted by how sure we are" — 5 reviews all positive scores
# ~0.48, not 1.0, so it cannot outrank 2,000 reviews at 92%.
WILSON_Z = 1.96
# Added to a game's age before dividing. Without it a game released yesterday
# with 20 reviews reads as 20 reviews/day and tops the chart on one day of
# noise; with it, 2.5/day.
SMOOTHING_DAYS = 7


def wilson_lower_bound(positive: int, total: int, z: float = WILSON_Z) -> float:
    """Lower bound of the 95% confidence interval on the positive rate.

    Python twin of the SQL in `_wilson_sql`. Ranking happens in the database —
    it is over 12,053 games and only the top N are returned — so the formula
    exists twice on purpose. Both are driven by WILSON_Z, and the tests pin
    this one's numbers.
    """
    if total <= 0:
        return 0.0
    p = positive / total
    denominator = 1 + z * z / total
    centre = p + z * z / (2 * total)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
    return max(0.0, (centre - margin) / denominator)


def _wilson_sql(positive, total):
    """The same interval as a SQL expression, for ORDER BY."""
    n = sa.cast(sa.func.nullif(total, 0), sa.Float)
    p = sa.cast(positive, sa.Float) / n
    z = WILSON_Z
    centre = p + z * z / (2 * n)
    margin = z * sa.func.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return (centre - margin) / (1 + z * z / n)


def _days_on_sale_sql():
    """Days since release, floored at 1 so a launch-day game is not divided by
    zero. Every game in this catalogue is a 2026 release, so this is a real
    age rather than a decade of accumulated back-catalogue."""
    return sa.func.greatest(1, sa.func.current_date() - Game.release_date)


async def trending_released(
    db: AsyncSession, limit: int, genre: str | None, tag: str | None
) -> dict:
    """Released games gaining traction fastest, weighted by reception.

        score = reviews_per_day x wilson_lower_bound(positive rate)

    Sorting on review COUNT alone would return the same handful of biggest
    games forever — that is a leaderboard, not a trend. Dividing by days on
    sale asks how fast a game is accumulating reviews rather than how many it
    has ever had, which is what makes a three-week-old game visible next to a
    seven-month-old one.

    The Wilson term is what stops velocity alone deciding it. A game pulling
    500 reviews a day at 40% positive is moving, but it is not a signal worth
    building a concept on; multiplying by the lower bound of its positive rate
    discounts it to the level of a slower, well-received game. The bound also
    handles small samples: 5 reviews at 100% scores below 2,000 at 92%.

    `reviews_per_day` is a lifetime average, not current velocity. Only 1,533
    of 23,076 games have two stats snapshots, so a measured recent rate does
    not exist for the catalogue yet.
    """
    ls = latest_stats_sq()
    conds = [Game.is_released.is_(True), Game.release_date.is_not(None)]
    conds += _scope(None, genre, tag)

    days = _days_on_sale_sql()
    per_day = sa.cast(ls.c.total_reviews, sa.Float) / (days + SMOOTHING_DAYS)
    quality = _wilson_sql(ls.c.positive_reviews, ls.c.total_reviews)
    score = (per_day * quality).label("score")

    rows = (
        await db.execute(
            sa.select(
                Game.appid,
                Game.name,
                Game.release_date,
                Game.current_price_cents,
                ls.c.total_reviews,
                ls.c.positive_reviews,
                ls.c.positive_pct,
                ls.c.peak_ccu,
                days.label("days_on_sale"),
                per_day.label("reviews_per_day"),
                quality.label("quality"),
                score,
            )
            .select_from(Game)
            .join(ls, ls.c.appid == Game.appid)
            .where(
                *conds,
                ls.c.total_reviews.is_not(None),
                ls.c.total_reviews > 0,
                ls.c.positive_reviews.is_not(None),
            )
            .order_by(score.desc())
            .limit(limit)
        )
    ).all()

    return {
        "segment": "released",
        "algorithm": (
            "reviews_per_day x wilson_lower_bound(positive rate). Velocity, "
            "discounted by how well received and how certain that reception is. "
            "reviews_per_day is a lifetime average — measured recent velocity "
            "does not exist for this catalogue yet."
        ),
        "items": [
            {
                "appid": r.appid,
                "name": r.name,
                "release_date": r.release_date,
                "is_released": True,
                "price_cents": r.current_price_cents,
                "total_reviews": r.total_reviews,
                "positive_reviews": r.positive_reviews,
                "positive_pct": float(r.positive_pct) if r.positive_pct is not None else None,
                "peak_ccu": r.peak_ccu,
                "days_on_sale": r.days_on_sale,
                "reviews_per_day": round(float(r.reviews_per_day), 3),
                "quality": round(float(r.quality), 4),
                "score": round(float(r.score), 4),
            }
            for r in rows
        ],
    }


async def trending_upcoming(
    db: AsyncSession, limit: int, genre: str | None, tag: str | None
) -> dict:
    """Unreleased games by wishlist demand.

    An unreleased game has no reviews, so the released algorithm has nothing to
    work with. What Steam does expose is Valve's Top-Wishlists chart, which is
    ordered by wishlists blended with recent velocity — the closest thing to a
    wishlist signal that exists first-party.

    **It is a position, not a count.** This project holds no wishlist number
    for any game except the 427 whose developers stated one publicly, and it
    will not derive one from rank or followers. So the ranking is the chart's
    own order, not a modelled quantity.

    Two tiers rather than one blended score: the 1,189 games on the chart come
    first in chart order, then the rest by follower count. Blending a rank with
    a follower count would need an exchange rate between them that nobody has
    validated — precisely the modelling this project refuses. `rank_basis` says
    which tier a game came from.
    """
    lf, pf = latest_followers_sq(), prior_followers_sq()
    lr, pr = latest_rank_sq(), prior_rank_sq()
    conds = [Game.is_released.is_(False)]
    conds += _scope(None, genre, tag)

    follower_delta = (lf.c.followers - pf.c.followers).label("follower_delta")
    rank_delta = (pr.c.rank - lr.c.rank).label("rank_delta")

    stmt = (
        sa.select(
            Game.appid,
            Game.name,
            Game.release_date,
            Game.current_price_cents,
            lr.c.rank.label("wishlist_rank"),
            rank_delta,
            lf.c.followers,
            follower_delta,
        )
        .select_from(Game)
        .outerjoin(lr, lr.c.appid == Game.appid)
        .outerjoin(pr, pr.c.appid == Game.appid)
        .outerjoin(lf, lf.c.appid == Game.appid)
        .outerjoin(pf, pf.c.appid == Game.appid)
        .where(*conds, sa.or_(lr.c.rank.is_not(None), lf.c.followers.is_not(None)))
    )

    moved = (
        await db.execute(
            sa.select(sa.func.count()).select_from(
                stmt.where(rank_delta.is_not(None)).subquery()
            )
        )
    ).scalar_one()

    if moved:
        # Chart movement is the real demand momentum signal: a game climbing
        # the Top-Wishlists chart is gaining wishlists faster than the games
        # around it.
        basis = "chart_movement"
        ordered = stmt.order_by(
            sa.desc(sa.func.coalesce(rank_delta, -(10**9))),
            sa.asc(sa.func.coalesce(lr.c.rank, 10**9)),
        )
    else:
        basis = "chart_position"
        ordered = stmt.order_by(
            # Charted games first, in chart order; then everything else by
            # followers. NULLS LAST on the rank does this in one clause.
            sa.asc(sa.func.coalesce(lr.c.rank, 10**9)),
            sa.desc(sa.func.coalesce(lf.c.followers, 0)),
        )

    rows = (await db.execute(ordered.limit(limit))).all()
    return {
        "segment": "upcoming",
        "basis": basis,
        "algorithm": (
            "Valve's Top-Wishlists chart order for the games on it, then "
            "remaining games by community-hub followers. Rank is an ORDER "
            "blending total wishlists with velocity, never a count — this "
            "dataset holds no wishlist number except developer disclosures."
        ),
        "items": [
            {
                "appid": r.appid,
                "name": r.name,
                "release_date": r.release_date,
                "is_released": False,
                "price_cents": r.current_price_cents,
                "wishlist_rank": r.wishlist_rank,
                "rank_delta_7d": r.rank_delta,
                "followers": r.followers,
                "follower_delta_14d": r.follower_delta,
                "rank_basis": "wishlist_chart" if r.wishlist_rank else "followers",
            }
            for r in rows
        ],
    }


async def _facet_stats(db: AsyncSession, joins, label_column, extra_conds, limit: int):
    """Supply, measured outcome and demand presence for one taxonomy facet.

    One query per facet family rather than per facet: a genre table with 20
    rows would otherwise be 20 round trips, and a tag table 429.
    """
    cpr = cohort_percentile_sq()
    lf, lr = latest_followers_sq(), latest_rank_sq()
    top_decile = sa.case((cpr.c.pr >= 0.9, 1), else_=0)

    stmt = (
        sa.select(
            label_column.label("key"),
            sa.func.count(sa.distinct(Game.appid)).label("games"),
            sa.func.count(sa.distinct(Game.appid))
            .filter(Game.is_released.is_(True))
            .label("released"),
            sa.func.count(sa.distinct(Game.appid))
            .filter(Game.is_released.is_(False))
            .label("upcoming"),
            _median(cpr.c.total_reviews).label("median_reviews"),
            _p90(cpr.c.total_reviews).label("p90_reviews"),
            sa.func.count(cpr.c.appid).label("ranked_sample"),
            sa.func.sum(top_decile).label("top_decile"),
            _median(Game.current_price_cents).label("median_price_cents"),
            sa.func.count(sa.distinct(lf.c.appid)).label("with_followers"),
            _median(lf.c.followers).label("median_followers"),
            sa.func.count(sa.distinct(lr.c.appid)).label("on_chart"),
            sa.func.min(lr.c.rank).label("best_rank"),
        )
        .select_from(Game)
    )
    for target, onclause in joins:
        stmt = stmt.join(target, onclause)
    stmt = (
        stmt.outerjoin(cpr, cpr.c.appid == Game.appid)
        .outerjoin(lf, lf.c.appid == Game.appid)
        .outerjoin(lr, lr.c.appid == Game.appid)
        .group_by(label_column)
        .order_by(sa.func.count(sa.distinct(Game.appid)).desc())
        .limit(limit)
    )
    if extra_conds:
        stmt = stmt.where(*extra_conds)

    rows = (await db.execute(stmt)).all()
    return [_facet_row(r) for r in rows]


def _facet_row(r) -> dict:
    sample = r.ranked_sample or 0
    return {
        "key": r.key,
        "games": r.games,
        "released": r.released,
        "upcoming": r.upcoming,
        "median_reviews": _num(r.median_reviews),
        "p90_reviews": _num(r.p90_reviews),
        # Share of this facet's RANKABLE games sitting in the top decile of
        # their release-month cohort. Not a success rate for the facet as a
        # whole: unreleased games and games with no reviews are not in it.
        "top_decile_share": (
            round((r.top_decile or 0) / sample, 4) if sample else None
        ),
        "outcome_sample": sample,
        "median_price_cents": _num(r.median_price_cents),
        "games_with_followers": r.with_followers,
        "median_followers": _num(r.median_followers),
        "games_on_wishlist_chart": r.on_chart,
        "best_wishlist_rank": r.best_rank,
        # Explicit rather than left to the reader: a facet this thin can show
        # any share at all and mean nothing.
        "sample_warning": (
            f"only {sample} rankable games — treat shares as indicative"
            if sample < MIN_FACET_SAMPLE
            else None
        ),
    }


def _num(value):
    if value is None:
        return None
    number = float(value)
    return round(number, 2) if number % 1 else int(number)


async def genres(db: AsyncSession, release_status: str | None, limit: int) -> list[dict]:
    conds = _scope(release_status, None, None)
    # Every catalogued game carries the Indie genre by construction, so the row
    # would just restate the catalogue.
    conds.append(Genre.name != "Indie")
    return await _facet_stats(
        db,
        [
            (game_genres, game_genres.c.appid == Game.appid),
            (Genre, Genre.id == game_genres.c.genre_id),
        ],
        Genre.name,
        conds,
        limit,
    )


async def tags(db: AsyncSession, release_status: str | None, limit: int) -> list[dict]:
    conds = _scope(release_status, None, None)
    return await _facet_stats(
        db,
        [
            (game_tags, game_tags.c.appid == Game.appid),
            (Tag, Tag.id == game_tags.c.tag_id),
        ],
        Tag.name,
        conds,
        limit,
    )


def _price_band_case():
    """Price → band key, in SQL so bucketing stays one query.

    Free games are their own band and are tested first, because Steam records
    them with no price rather than a price of zero — bucketing on cents alone
    would drop 2,264 free games into the same bin as unannounced ones.

    The remaining no-price games are overwhelmingly unreleased pages that have
    not announced a price. They are labelled as such rather than left null: an
    agent reading a `null` bucket of 8,405 games learns nothing, and one
    reading "unannounced" learns that most unreleased indie pages have no
    price yet.
    """
    branches = [(Game.is_free.is_(True), "free")]
    for key, low, high in PRICE_BANDS:
        if key == "free":
            continue
        if high is None:
            branches.append((Game.current_price_cents >= low, key))
        else:
            branches.append(
                (sa.and_(Game.current_price_cents >= low, Game.current_price_cents <= high), key)
            )
    return sa.case(*branches, else_=sa.literal("unannounced"))


# The design axes this catalogue classifies, plus the commercial choices that
# sit alongside them. Each is a column or expression to group by.
DESIGN_AXES = {
    "dimension": lambda: Game.dimension,
    "camera": lambda: Game.camera,
    "graphics_style": lambda: Game.graphics_style,
    "engine": lambda: Game.engine,
    "price_band": _price_band_case,
    "early_access": lambda: Game.early_access,
    "demo_available": lambda: Game.demo_available,
}


async def design_attributes(
    db: AsyncSession, axis: str, release_status: str | None
) -> list[dict]:
    """How each value of one design axis has actually performed.

    The honest reading is comparative, not causal: 'top-down pixel-art games
    rank higher' describes what shipped, not what would happen if a different
    game adopted the style. Selection is doing work here that no query can
    separate out.
    """
    column = DESIGN_AXES[axis]()
    cpr = cohort_percentile_sq()
    lf = latest_followers_sq()
    top_decile = sa.case((cpr.c.pr >= 0.9, 1), else_=0)

    stmt = (
        sa.select(
            column.label("key"),
            sa.func.count(sa.distinct(Game.appid)).label("games"),
            sa.func.count(sa.distinct(Game.appid))
            .filter(Game.is_released.is_(True))
            .label("released"),
            sa.func.count(sa.distinct(Game.appid))
            .filter(Game.is_released.is_(False))
            .label("upcoming"),
            _median(cpr.c.total_reviews).label("median_reviews"),
            _p90(cpr.c.total_reviews).label("p90_reviews"),
            sa.func.count(cpr.c.appid).label("ranked_sample"),
            sa.func.sum(top_decile).label("top_decile"),
            _median(Game.current_price_cents).label("median_price_cents"),
            sa.func.count(sa.distinct(lf.c.appid)).label("with_followers"),
            _median(lf.c.followers).label("median_followers"),
            sa.literal(None).label("on_chart"),
            sa.literal(None).label("best_rank"),
        )
        .select_from(Game)
        .outerjoin(cpr, cpr.c.appid == Game.appid)
        .outerjoin(lf, lf.c.appid == Game.appid)
        .group_by(column)
        .order_by(sa.func.count(sa.distinct(Game.appid)).desc())
    )
    conds = _scope(release_status, None, None)
    if conds:
        stmt = stmt.where(*conds)

    rows = (await db.execute(stmt)).all()
    out = []
    for r in rows:
        row = _facet_row(r)
        key = r.key
        row["key"] = key.value if hasattr(key, "value") else str(key)
        # These two are meaningless for a design axis — a bucket is not a
        # chart entry — so drop them rather than report null columns.
        row.pop("games_on_wishlist_chart", None)
        row.pop("best_wishlist_rank", None)
        out.append(row)
    return out


async def landscape(
    db: AsyncSession,
    genres_in: list[str],
    tags_in: list[str],
    release_status: str | None,
    competitor_limit: int,
) -> dict:
    """The competitive field a concept would ship into.

    Answers the question a pitch has to survive: how many games already do
    this, how did they do, what do they charge, and what else do they carry
    that this concept does not.
    """
    conds: list = []
    for genre in genres_in:
        conds.extend(_scope(None, genre, None))
    for tag in tags_in:
        conds.extend(_scope(None, None, tag))
    conds.extend(_scope(release_status, None, None))
    if not conds:
        conds = [sa.true()]

    cpr = cohort_percentile_sq()
    lf, lr = latest_followers_sq(), latest_rank_sq()
    top_decile = sa.case((cpr.c.pr >= 0.9, 1), else_=0)

    field = (
        await db.execute(
            sa.select(
                sa.literal("field").label("key"),
                sa.func.count(sa.distinct(Game.appid)).label("games"),
                sa.func.count(sa.distinct(Game.appid))
                .filter(Game.is_released.is_(True))
                .label("released"),
                sa.func.count(sa.distinct(Game.appid))
                .filter(Game.is_released.is_(False))
                .label("upcoming"),
                _median(cpr.c.total_reviews).label("median_reviews"),
                _p90(cpr.c.total_reviews).label("p90_reviews"),
                sa.func.count(cpr.c.appid).label("ranked_sample"),
                sa.func.sum(top_decile).label("top_decile"),
                _median(Game.current_price_cents).label("median_price_cents"),
                sa.func.count(sa.distinct(lf.c.appid)).label("with_followers"),
                _median(lf.c.followers).label("median_followers"),
                sa.func.count(sa.distinct(lr.c.appid)).label("on_chart"),
                sa.func.min(lr.c.rank).label("best_rank"),
            )
            .select_from(Game)
            .outerjoin(cpr, cpr.c.appid == Game.appid)
            .outerjoin(lf, lf.c.appid == Game.appid)
            .outerjoin(lr, lr.c.appid == Game.appid)
            .where(*conds)
        )
    ).one()

    competitors = (
        await db.execute(
            sa.select(
                Game.appid,
                Game.name,
                Game.release_date,
                Game.is_released,
                Game.current_price_cents,
                cpr.c.total_reviews,
                cpr.c.pr,
                lf.c.followers,
                lr.c.rank.label("wishlist_rank"),
            )
            .select_from(Game)
            .join(cpr, cpr.c.appid == Game.appid)
            .outerjoin(lf, lf.c.appid == Game.appid)
            .outerjoin(lr, lr.c.appid == Game.appid)
            .where(*conds)
            .order_by(cpr.c.total_reviews.desc())
            .limit(competitor_limit)
        )
    ).all()

    # What else the games in this field are tagged with — the adjacent design
    # space, and the most direct answer to "what goes with this".
    adjacent = (
        await db.execute(
            sa.select(Tag.name, sa.func.count(sa.distinct(Game.appid)).label("games"))
            .select_from(Game)
            .join(game_tags, game_tags.c.appid == Game.appid)
            .join(Tag, Tag.id == game_tags.c.tag_id)
            .where(*conds)
            .group_by(Tag.name)
            .order_by(sa.func.count(sa.distinct(Game.appid)).desc())
            .limit(20)
        )
    ).all()

    wanted = {t.strip().lower() for t in tags_in}
    return {
        "field": _facet_row(field),
        "competitors": [
            {
                "appid": c.appid,
                "name": c.name,
                "release_date": c.release_date,
                "is_released": c.is_released,
                "price_cents": c.current_price_cents,
                "total_reviews": c.total_reviews,
                "cohort_percentile": round(float(c.pr), 4) if c.pr is not None else None,
                "followers": c.followers,
                "wishlist_rank": c.wishlist_rank,
            }
            for c in competitors
        ],
        "adjacent_tags": [
            {"tag": name, "games": games}
            for name, games in adjacent
            if name.strip().lower() not in wanted
        ],
    }


async def unknown_taxonomy(
    db: AsyncSession, genres_in: list[str], tags_in: list[str]
) -> list[dict]:
    """Requested genre/tag names that do not exist, each with near misses.

    Worth the extra round trip because the failure it prevents is silent and
    severe: an agent guessing "Deckbuilder" (the real tag is "Deckbuilding")
    would otherwise get a field of zero games and read it as an empty market
    rather than a typo — then pitch a concept into a space that already holds
    874 titles.
    """
    problems = []
    for column, wanted, kind in ((Genre.name, genres_in, "genre"), (Tag.name, tags_in, "tag")):
        for raw in wanted:
            name = raw.strip()
            exists = await db.scalar(
                sa.select(column).where(sa.func.lower(column) == name.lower()).limit(1)
            )
            if exists:
                continue
            near = (
                await db.execute(
                    sa.select(column)
                    .where(column.ilike(f"%{name}%"))
                    .order_by(sa.func.length(column))
                    .limit(8)
                )
            ).scalars().all()
            problems.append({"kind": kind, "requested": name, "did_you_mean": list(near)})
    return problems
