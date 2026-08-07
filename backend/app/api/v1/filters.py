import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models import (
    Camera,
    DataStatus,
    Developer,
    Dimension,
    Game,
    GameEngine,
    Genre,
    GraphicsStyle,
    Publisher,
    Tag,
    game_tags,
)
from app.schemas.game import FilterOptions

router = APIRouter()

TOP_TAGS = 100


@router.get("/options", response_model=FilterOptions)
async def filter_options(db: AsyncSession = Depends(get_db)) -> FilterOptions:
    genres = (
        (await db.execute(sa.select(Genre.name).order_by(Genre.name))).scalars().all()
    )
    top_tags = (
        (
            await db.execute(
                sa.select(Tag.name)
                .join(game_tags, game_tags.c.tag_id == Tag.id)
                .group_by(Tag.id, Tag.name)
                .order_by(sa.func.count(game_tags.c.appid).desc())
                .limit(TOP_TAGS)
            )
        )
        .scalars()
        .all()
    )
    months = (
        (
            await db.execute(
                sa.select(sa.distinct(sa.extract("month", Game.release_date)))
                .where(Game.release_date.is_not(None))
                .order_by(sa.extract("month", Game.release_date).asc())
            )
        )
        .scalars()
        .all()
    )
    return FilterOptions(
        genres=list(genres),
        tags=list(top_tags),
        engines=[e.value for e in GameEngine],
        dimensions=[d.value for d in Dimension],
        cameras=[c.value for c in Camera],
        graphics_styles=[g.value for g in GraphicsStyle],
        data_statuses=[s.value for s in DataStatus],
        release_months=[int(m) for m in months if m is not None],
    )


@router.get("/companies", response_model=list[str])
async def search_companies(
    db: AsyncSession = Depends(get_db),
    role: str = Query("developer", pattern="^(developer|publisher)$"),
    q: str = Query("", description="name prefix/substring"),
    limit: int = Query(50, ge=1, le=200),
) -> list[str]:
    model = Developer if role == "developer" else Publisher
    stmt = sa.select(model.name).order_by(model.name).limit(limit)
    if q:
        stmt = stmt.where(model.name.ilike(f"%{q}%"))
    return list((await db.execute(stmt)).scalars().all())
