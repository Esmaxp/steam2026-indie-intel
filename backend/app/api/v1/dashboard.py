import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models import Dimension, Game
from app.schemas.game import AverageStat, DashboardSummary
from app.services.games_query import (
    latest_revenue_sq,
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


@router.get("/summary", response_model=DashboardSummary)
async def summary(db: AsyncSession = Depends(get_db)) -> DashboardSummary:
    ls, lw, lr = latest_stats_sq(), latest_wishlist_sq(), latest_revenue_sq()
    return DashboardSummary(
        total_games=await _count(db),
        released_games=await _count(db, Game.is_released.is_(True)),
        coming_soon_games=await _count(db, Game.coming_soon.is_(True)),
        two_d_games=await _count(db, Game.dimension == Dimension.TWO_D),
        three_d_games=await _count(db, Game.dimension == Dimension.THREE_D),
        games_with_demo=await _count(db, Game.demo_available.is_(True)),
        next_fest_games=await _count(db, next_fest_exists()),
        avg_reviews=await _avg(db, ls.c.total_reviews),
        avg_wishlist=await _avg(db, lw.c.wishlist_count),
        avg_revenue=await _avg(db, lr.c.gross_revenue_usd),
    )
