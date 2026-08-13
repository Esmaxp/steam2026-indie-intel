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


async def trending(
    db: AsyncSession,
    limit: int,
    release_status: str | None,
    genre: str | None,
    tag: str | None,
) -> dict:
    """Games with the strongest recent demand movement.

    Momentum needs two observations separated by time. Where that does not
    exist yet the games are ranked by current standing instead — a point-in-
    time signal — and `basis` says which of the two produced the list, because
    "rising fast" and "currently big" are different claims and an agent
    building a concept off the wrong one would be misled.
    """
    lf, pf = latest_followers_sq(), prior_followers_sq()
    lr, pr = latest_rank_sq(), prior_rank_sq()
    ls = latest_stats_sq()
    conds = _scope(release_status, genre, tag)

    follower_delta = (lf.c.followers - pf.c.followers).label("follower_delta")
    # Rank improves as the number falls, so prior minus latest is the gain.
    rank_delta = (pr.c.rank - lr.c.rank).label("rank_delta")

    stmt = (
        sa.select(
            Game.appid,
            Game.name,
            Game.release_date,
            Game.is_released,
            Game.current_price_cents,
            lf.c.followers,
            follower_delta,
            lr.c.rank.label("wishlist_rank"),
            rank_delta,
            ls.c.total_reviews,
            ls.c.positive_pct,
        )
        .select_from(Game)
        .outerjoin(lf, lf.c.appid == Game.appid)
        .outerjoin(pf, pf.c.appid == Game.appid)
        .outerjoin(lr, lr.c.appid == Game.appid)
        .outerjoin(pr, pr.c.appid == Game.appid)
        .outerjoin(ls, ls.c.appid == Game.appid)
    )
    if conds:
        stmt = stmt.where(*conds)

    movers = sa.or_(follower_delta.is_not(None), rank_delta.is_not(None))
    measured = (await db.execute(
        sa.select(sa.func.count()).select_from(stmt.where(movers).subquery())
    )).scalar_one()

    if measured:
        basis = "movement"
        ordered = stmt.where(movers).order_by(
            sa.desc(sa.func.coalesce(follower_delta, 0) + sa.func.coalesce(rank_delta, 0))
        )
    else:
        # Nothing has moved measurably yet. Fall back to current standing and
        # label it, rather than return an empty list that reads as a flat market.
        basis = "current_standing"
        ordered = stmt.where(
            sa.or_(lf.c.followers.is_not(None), lr.c.rank.is_not(None))
        ).order_by(
            sa.asc(sa.func.coalesce(lr.c.rank, 10**9)),
            sa.desc(sa.func.coalesce(lf.c.followers, 0)),
        )

    rows = (await db.execute(ordered.limit(limit))).all()
    return {
        "basis": basis,
        "items": [
            {
                "appid": r.appid,
                "name": r.name,
                "release_date": r.release_date,
                "is_released": r.is_released,
                "price_cents": r.current_price_cents,
                "followers": r.followers,
                "follower_delta_14d": r.follower_delta,
                "wishlist_rank": r.wishlist_rank,
                "rank_delta_7d": r.rank_delta,
                "total_reviews": r.total_reviews,
                "positive_pct": float(r.positive_pct) if r.positive_pct is not None else None,
                "signals": [
                    name
                    for name, value in (
                        ("follower_growth", r.follower_delta),
                        ("rank_improvement", r.rank_delta),
                    )
                    if value is not None and value > 0
                ],
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
