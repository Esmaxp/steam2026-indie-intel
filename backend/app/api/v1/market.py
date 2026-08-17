"""Market intelligence for the Game Market Analyzer agent.

A purpose-built read surface. The existing `/games` endpoints already expose
everything per game, but an agent asking "what should we build" does not want
23,078 rows — it wants the aggregate that answers the question, small enough to
reason over and carrying enough context that it cannot be misread.

Three things every response here does deliberately:

- states its own COVERAGE, so a thin result reads as "the signal is young"
  rather than "the market is quiet"
- labels which BASIS produced a ranking, because "rising fast" and "currently
  big" are different claims
- carries no estimated wishlist or revenue figure, because none exists to
  carry. See /market/manifest for the full rule.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.market import (
    CoverageOut,
    DesignAxisOut,
    FacetOut,
    LandscapeOut,
    ManifestOut,
    TrendingOut,
)
from app.services import market, success_bands

router = APIRouter()

RELEASE_STATUS = Query(
    None,
    pattern="^(released|upcoming)$",
    description="Limit to released or unreleased games. Omit for both.",
)


async def _reject_unknown(db: AsyncSession, genres: list[str], tags: list[str]) -> None:
    """Fail loudly on a name that is not in the taxonomy.

    An unknown filter silently matches nothing, and a field of zero games
    reads as an empty market rather than a typo. For an agent that guesses
    vocabulary that is the difference between "untapped niche" and "874
    competitors".
    """
    problems = await market.unknown_taxonomy(db, genres, tags)
    if problems:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "unknown genre or tag",
                "problems": problems,
                "hint": "Exact names only. GET /api/v1/filters/options lists every "
                "genre and tag in the catalogue.",
            },
        )


@router.get("/manifest", response_model=ManifestOut)
async def manifest(db: AsyncSession = Depends(get_db)) -> ManifestOut:
    """What this tool can answer, what each number means, and what it will
    never provide. Call this first.

    An agent that starts from the raw endpoints will eventually infer a
    wishlist figure from followers, or read a top-decile share as a success
    rate. Both are wrong, and neither is obvious from a JSON payload — so the
    constraints ship as data rather than living in a README.
    """
    return ManifestOut(
        purpose=(
            "First-party Steam market intelligence for 2026 indie games: what is "
            "shipping, what is being demanded, and how released games have actually "
            "performed. Intended as the evidence layer under game-concept work."
        ),
        rules=[
            (
                "No wishlist count is estimated, ever. A game shows a developer-"
                "disclosed figure with a source link and date, or it shows nothing. "
                "Do not derive one from followers, rank, or reviews — no third-party "
                "wishlist model has ever been validated in public against a real "
                "Steamworks number."
            ),
            (
                "Revenue and copies ARE estimated, but only as a RANGE, only from "
                "signals this project measures itself, and always with the formula "
                "and inputs attached. Quote the band, never its midpoint as a fact, "
                "and never a figure for a game with fewer than 10 reviews or a "
                "free-to-play title — neither is estimated at all. Steam still "
                "publishes no sales number; these are derived and labelled "
                "`estimated`, which is not the same kind of claim as a review count."
            ),
            (
                "Outcome is expressed as POSITION among release-month peers, not as "
                "sales. 'Top decile' means nine in ten games released that month have "
                "fewer reviews. It says nothing about revenue, quality or profit."
            ),
            (
                "Facet comparisons are descriptive, not causal. That a style ranks "
                "well describes what shipped in it, not what would happen if a new "
                "game adopted it — selection effects are doing work no query can "
                "separate out."
            ),
            (
                "Check `coverage` before concluding anything from a short list. A "
                "signal that needs two observations over time may simply not exist yet."
            ),
        ],
        metrics={
            "total_reviews": "Steam's own published review count. Measured, dense — the "
            "most reliable outcome signal here.",
            "positive_pct": "Share of reviews that are positive, as published by Steam.",
            "cohort_percentile": "Position among games released the same month, by review "
            "count. 0.9 = top decile of that month.",
            "followers": "Steam community-hub members. A count Valve publishes; exact, "
            "not modelled. A demand proxy, not a wishlist count.",
            "follower_delta_14d": "Change across our own snapshots. Absent until two "
            "snapshots exist at least 14 days apart.",
            "wishlist_rank": "Position on Valve's Top-Wishlists chart — an ORDER blending "
            "total wishlists with recent velocity, not a count. Roughly 5.2k games across "
            "all of Steam are on it; 'not ranked' is the normal case.",
            "rank_delta_7d": "Chart positions gained since the newest complete sweep at "
            "least 7 days old. Positive = moved up.",
            "reviews_per_day": "Total reviews over days on sale, plus a 7-day smoothing "
            "term. A lifetime average, not current velocity — only 1,533 of 23,076 games "
            "have two stats snapshots, so a measured recent rate does not exist yet.",
            "quality": "Wilson lower bound of the positive rate at 95%. Combines how "
            "positive with how certain: 5 reviews at 100% scores ~0.48, below 2,000 at 92%.",
            "score": "The released trending rank: reviews_per_day x quality. Velocity "
            "discounted by reception, so a fast but badly received game does not read as "
            "a success.",
            "revenue": "A derived RANGE in USD, not a measurement. Solved from review "
            "count, cross-checked against followers and peak concurrents, with the "
            "formula and inputs stored alongside. Absent below 10 reviews and for "
            "free-to-play games. Carries a provenance status like every other "
            "business metric — read it before quoting the number.",
            "median_price_cents": "Median current price of games in the facet, in cents.",
            "top_decile_share": "Share of the facet's RANKABLE games in the top decile of "
            "their release-month cohort. Denominator excludes unreleased games and games "
            "with no reviews — it is not a success rate for the facet as a whole.",
        },
        endpoints=[
            {
                "path": "/api/v1/market/coverage",
                "use_when": "Before trusting any thin result. Says which signals exist.",
            },
            {
                "path": "/api/v1/market/trending?segment=released",
                "use_when": "Released games gaining traction fastest: reviews per day "
                "weighted by the Wilson lower bound of the positive rate.",
            },
            {
                "path": "/api/v1/market/trending?segment=upcoming",
                "use_when": "Pre-release demand: Valve's Top-Wishlists chart order, then "
                "remaining games by followers. Check `basis` before calling it 'rising'.",
            },
            {
                "path": "/api/v1/market/genres",
                "use_when": "Coarse supply/demand picture across the 20 Steam genres.",
            },
            {
                "path": "/api/v1/market/tags",
                "use_when": "The real design vocabulary — 429 tags. Use for concept work; "
                "genres are too coarse to describe a game.",
            },
            {
                "path": "/api/v1/market/design-attributes",
                "use_when": "How a design choice (dimension, camera, art style, engine, "
                "price band, early access, demo) has performed.",
            },
            {
                "path": "/api/v1/market/landscape",
                "use_when": "Sizing the competitive field for a specific concept, with "
                "direct competitors and the adjacent tag space.",
            },
            {
                "path": "/api/v1/games",
                "use_when": "Drilling into individual games. Rich filters and sorts; see "
                "the OpenAPI schema at /openapi.json.",
            },
            {
                "path": "/api/v1/games/{appid}",
                "use_when": "Full detail on one game, including provenance for every "
                "business metric.",
            },
            {
                "path": "/api/v1/games/{appid}/similar",
                "use_when": "Finding comparable titles for a concept already in the "
                "catalogue.",
            },
            {
                "path": "/api/v1/dashboard/genre-success",
                "use_when": "The full success-band distribution for one genre.",
            },
        ],
        success_bands=[
            {"key": band.key, "label": band.label, "min_percentile": band.min_percentile}
            for band in success_bands.SUCCESS_BANDS
        ],
        method_notes=success_bands.NOTES,
        coverage=CoverageOut(**await market.coverage(db)),
    )


@router.get("/coverage", response_model=CoverageOut)
async def coverage(db: AsyncSession = Depends(get_db)) -> CoverageOut:
    """Which signals actually exist right now, and how densely."""
    return CoverageOut(**await market.coverage(db))


@router.get("/trending", response_model=TrendingOut)
async def trending(
    db: AsyncSession = Depends(get_db),
    segment: str = Query(
        ...,
        pattern="^(released|upcoming)$",
        description="Which market to rank. Required, because the two are ranked by "
        "different algorithms and a blended list would be meaningless.",
    ),
    limit: int = Query(25, ge=1, le=100),
    genre: str | None = Query(None, description="Restrict to one genre, case-insensitive"),
    tag: str | None = Query(None, description="Restrict to one Steam tag, case-insensitive"),
) -> TrendingOut:
    """Games gaining traction, ranked by the signals their segment actually has.

    **released** — `reviews_per_day x wilson_lower_bound(positive rate)`.
    Velocity rather than total, so a leaderboard of the biggest games does not
    crowd out what is moving; multiplied by the lower bound of the positive
    rate so a fast-but-poorly-received game does not read as a success and a
    5-review game cannot beat a 2,000-review one.

    **upcoming** — Valve's Top-Wishlists chart order, then remaining games by
    followers. An unreleased game has no reviews; the chart is the only
    first-party wishlist signal that exists. It is a POSITION, not a count, and
    nothing here converts it into one.

    `algorithm` restates the ranking in the payload, so a consumer that only
    ever sees JSON knows what it is reading.
    """
    await _reject_unknown(db, [genre] if genre else [], [tag] if tag else [])
    if segment == "released":
        result = await market.trending_released(db, limit, genre, tag)
    else:
        result = await market.trending_upcoming(db, limit, genre, tag)
    return TrendingOut(
        segment=result["segment"],
        algorithm=result["algorithm"],
        basis=result.get("basis"),
        items=result["items"],
        coverage=CoverageOut(**await market.coverage(db)),
    )


@router.get("/genres", response_model=list[FacetOut])
async def genres(
    db: AsyncSession = Depends(get_db),
    release_status: str | None = RELEASE_STATUS,
    limit: int = Query(30, ge=1, le=100),
) -> list[FacetOut]:
    """Supply, measured outcome and demand presence per Steam genre.

    The Indie genre is omitted: every game in this catalogue carries it by
    construction, so the row would restate the catalogue.
    """
    return [FacetOut(**row) for row in await market.genres(db, release_status, limit)]


@router.get("/tags", response_model=list[FacetOut])
async def tags(
    db: AsyncSession = Depends(get_db),
    release_status: str | None = RELEASE_STATUS,
    limit: int = Query(60, ge=1, le=200),
) -> list[FacetOut]:
    """The same per Steam tag — the vocabulary that actually describes a game.

    Ordered by how many games carry the tag, so the head of the list is the
    crowded space and the tail is where a concept has room. Read
    `top_decile_share` next to `outcome_sample`: a tag with a dozen rankable
    games can show any share at all.
    """
    return [FacetOut(**row) for row in await market.tags(db, release_status, limit)]


@router.get("/design-attributes", response_model=DesignAxisOut)
async def design_attributes(
    db: AsyncSession = Depends(get_db),
    axis: str = Query(
        "dimension",
        description="One of: " + ", ".join(sorted(market.DESIGN_AXES)),
    ),
    release_status: str | None = RELEASE_STATUS,
) -> DesignAxisOut:
    """How each value of one design or commercial axis has performed.

    Descriptive only. Games are not assigned their art style at random, so the
    difference between two buckets includes everything else that differs about
    the teams who chose them.
    """
    if axis not in market.DESIGN_AXES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown axis '{axis}'. Try one of: {', '.join(sorted(market.DESIGN_AXES))}",
        )
    return DesignAxisOut(
        axis=axis,
        buckets=[
            FacetOut(**row) for row in await market.design_attributes(db, axis, release_status)
        ],
        caveat=(
            "Descriptive, not causal: this is how games that made each choice have "
            "done, not what the choice would do for a different game."
        ),
    )


@router.get("/landscape", response_model=LandscapeOut)
async def landscape(
    db: AsyncSession = Depends(get_db),
    genre: list[str] = Query(default=[], description="Repeatable. ANDed with tags."),
    tag: list[str] = Query(default=[], description="Repeatable. ANDed with genres."),
    release_status: str | None = RELEASE_STATUS,
    competitors: int = Query(15, ge=1, le=50),
) -> LandscapeOut:
    """The competitive field a concept would ship into.

    Filters are ANDed, so `?tag=Roguelike&tag=Deckbuilder` is the intersection —
    the games a concept would compete with directly, not the union of two
    genres. `adjacent_tags` is what those games ALSO carry, which is the most
    direct evidence of what pairs well with the space.
    """
    if not genre and not tag:
        raise HTTPException(
            status_code=422,
            detail="Give at least one genre or tag — an unfiltered landscape is the "
            "whole catalogue, which /market/coverage already reports.",
        )
    await _reject_unknown(db, genre, tag)
    result = await market.landscape(db, genre, tag, release_status, competitors)
    return LandscapeOut(
        genres=genre,
        tags=tag,
        field=FacetOut(**result["field"]),
        competitors=result["competitors"],
        adjacent_tags=result["adjacent_tags"],
    )
