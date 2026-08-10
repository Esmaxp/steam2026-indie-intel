"""'Find similar games' scoring (promt.md feature 2).

Similarity is derived ONLY from fields the collectors reliably populate:
shared genres, shared store tags (weighted by the source game's tag rank —
top tags matter most), matching classification attributes (dimension,
camera, graphics style, engine — counted only when the source value is not
'unknown'), a ±30% price window, and a small same-company bonus. A candidate
must share at least one genre or tag to appear at all; attribute/price
matches alone never qualify a game.
"""

from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Camera,
    Dimension,
    Game,
    GameEngine,
    GraphicsStyle,
    game_developers,
    game_genres,
    game_publishers,
    game_tags,
)
from app.services.games_query import GameFilters, build_games_query

TOP_TAGS = 20        # how many of the source game's top-ranked tags to use
WEIGHT_GENRE = 5     # per shared genre
WEIGHT_ATTR = 8      # per matching known classification attribute
WEIGHT_PRICE = 5     # price within ±30%
WEIGHT_COMPANY = 4   # shares a developer or publisher
PRICE_WINDOW = 0.30


@dataclass
class SourceGame:
    appid: int
    dimension: Dimension
    camera: Camera
    graphics_style: GraphicsStyle
    engine: GameEngine
    current_price_cents: int | None
    genre_ids: list[int] = field(default_factory=list)
    tag_weights: dict[int, int] = field(default_factory=dict)  # tag_id -> weight
    developer_ids: list[int] = field(default_factory=list)
    publisher_ids: list[int] = field(default_factory=list)


async def fetch_source(db: AsyncSession, appid: int) -> SourceGame | None:
    game = await db.get(Game, appid)
    if game is None:
        return None
    source = SourceGame(
        appid=appid,
        dimension=game.dimension,
        camera=game.camera,
        graphics_style=game.graphics_style,
        engine=game.engine,
        current_price_cents=game.current_price_cents,
    )
    source.genre_ids = list(
        (
            await db.execute(
                sa.select(game_genres.c.genre_id).where(game_genres.c.appid == appid)
            )
        ).scalars()
    )
    tag_rows = (
        await db.execute(
            sa.select(game_tags.c.tag_id, game_tags.c.rank)
            .where(game_tags.c.appid == appid)
            .order_by(game_tags.c.rank.asc().nulls_last())
            .limit(TOP_TAGS)
        )
    ).all()
    # Rank 1 (most voted) → weight TOP_TAGS, rank 20 → 1; unranked → 1.
    source.tag_weights = {
        tag_id: max(1, TOP_TAGS + 1 - rank) if rank else 1 for tag_id, rank in tag_rows
    }
    source.developer_ids = list(
        (
            await db.execute(
                sa.select(game_developers.c.developer_id).where(
                    game_developers.c.appid == appid
                )
            )
        ).scalars()
    )
    source.publisher_ids = list(
        (
            await db.execute(
                sa.select(game_publishers.c.publisher_id).where(
                    game_publishers.c.appid == appid
                )
            )
        ).scalars()
    )
    return source


def build_similar_query(source: SourceGame, limit: int, include_flagged: bool) -> sa.Select:
    base = build_games_query(GameFilters(include_flagged=include_flagged)).stmt

    tag_score_col = sa.literal(0)
    if source.tag_weights:
        tag_score_sq = (
            sa.select(
                game_tags.c.appid.label("appid"),
                sa.func.sum(
                    sa.case(
                        *[
                            (game_tags.c.tag_id == tag_id, weight)
                            for tag_id, weight in source.tag_weights.items()
                        ],
                        else_=0,
                    )
                ).label("tag_score"),
            )
            .where(game_tags.c.tag_id.in_(source.tag_weights))
            .group_by(game_tags.c.appid)
            .subquery("tag_scores")
        )
        base = base.outerjoin(tag_score_sq, tag_score_sq.c.appid == Game.appid)
        tag_score_col = sa.func.coalesce(tag_score_sq.c.tag_score, 0)

    genre_score_col = sa.literal(0)
    if source.genre_ids:
        genre_score_sq = (
            sa.select(
                game_genres.c.appid.label("appid"),
                (sa.func.count() * WEIGHT_GENRE).label("genre_score"),
            )
            .where(game_genres.c.genre_id.in_(source.genre_ids))
            .group_by(game_genres.c.appid)
            .subquery("genre_scores")
        )
        base = base.outerjoin(genre_score_sq, genre_score_sq.c.appid == Game.appid)
        genre_score_col = sa.func.coalesce(genre_score_sq.c.genre_score, 0)

    bonus_terms = []
    for column, value, unknown in (
        (Game.dimension, source.dimension, Dimension.UNKNOWN),
        (Game.camera, source.camera, Camera.UNKNOWN),
        (Game.graphics_style, source.graphics_style, GraphicsStyle.UNKNOWN),
        (Game.engine, source.engine, GameEngine.UNKNOWN),
    ):
        if value != unknown:
            bonus_terms.append(sa.case((column == value, WEIGHT_ATTR), else_=0))

    if source.current_price_cents:
        low = int(source.current_price_cents * (1 - PRICE_WINDOW))
        high = int(source.current_price_cents * (1 + PRICE_WINDOW))
        bonus_terms.append(
            sa.case((Game.current_price_cents.between(low, high), WEIGHT_PRICE), else_=0)
        )

    if source.developer_ids or source.publisher_ids:
        company_conds = []
        if source.developer_ids:
            company_conds.append(
                sa.exists(
                    sa.select(sa.literal(1)).where(
                        game_developers.c.appid == Game.appid,
                        game_developers.c.developer_id.in_(source.developer_ids),
                    )
                )
            )
        if source.publisher_ids:
            company_conds.append(
                sa.exists(
                    sa.select(sa.literal(1)).where(
                        game_publishers.c.appid == Game.appid,
                        game_publishers.c.publisher_id.in_(source.publisher_ids),
                    )
                )
            )
        bonus_terms.append(sa.case((sa.or_(*company_conds), WEIGHT_COMPANY), else_=0))

    content_score = tag_score_col + genre_score_col
    similarity = content_score
    for term in bonus_terms:
        similarity = similarity + term

    return (
        base.add_columns(similarity.label("similarity"))
        .where(Game.appid != source.appid, content_score > 0)
        .order_by(None)
        .order_by(sa.desc("similarity"), Game.appid)
        .limit(limit)
    )
