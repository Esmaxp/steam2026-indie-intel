import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models import DataStatus, Dimension, Game, Genre, game_genres
from app.schemas.charts import BreakdownPoint, ChartsOut, MonthPoint
from app.schemas.game import AverageStat, DashboardSummary
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
