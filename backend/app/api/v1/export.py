from pathlib import Path

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.serializers import row_to_list_item
from app.core.config import get_settings
from app.db.session import get_db
from app.models import (
    Camera,
    DataStatus,
    Dimension,
    Game,
    GameEngine,
    GraphicsStyle,
)
from app.services.export import EXPORT_ROW_CAP, MEDIA_TYPES, export_bytes
from app.services.games_query import GameFilters, build_games_query

router = APIRouter()

_LOAD_OPTIONS = (
    selectinload(Game.developers),
    selectinload(Game.publishers),
    selectinload(Game.genres),
    selectinload(Game.tags),
)


@router.get("")
async def export_games(
    db: AsyncSession = Depends(get_db),
    format: str = Query("csv", pattern="^(csv|xlsx|json|md)$"),
    q: str | None = None,
    developer: str | None = None,
    publisher: str | None = None,
    genre: str | None = None,
    tag: str | None = None,
    engine: GameEngine | None = None,
    dimension: Dimension | None = None,
    camera: Camera | None = None,
    graphics_style: GraphicsStyle | None = None,
    demo_available: bool | None = None,
    next_fest: bool | None = None,
    released: bool | None = None,
    early_access: bool | None = None,
    free: bool | None = None,
    release_month: int | None = Query(None, ge=1, le=12),
    min_reviews: int | None = Query(None, ge=0),
    min_positive_pct: float | None = Query(None, ge=0, le=100),
    min_peak_ccu: int | None = Query(None, ge=0),
    min_wishlist: int | None = Query(None, ge=0),
    min_revenue: float | None = Query(None, ge=0),
    wishlist_status: DataStatus | None = None,
    revenue_status: DataStatus | None = None,
    sort: str = "-release_date",
) -> Response:
    filters = GameFilters(
        q=q, developer=developer, publisher=publisher, genre=genre, tag=tag,
        engine=engine, dimension=dimension, camera=camera, graphics_style=graphics_style,
        demo_available=demo_available, next_fest=next_fest, released=released,
        early_access=early_access, free=free, release_month=release_month,
        min_reviews=min_reviews, min_positive_pct=min_positive_pct,
        min_peak_ccu=min_peak_ccu, min_wishlist=min_wishlist, min_revenue=min_revenue,
        wishlist_status=wishlist_status, revenue_status=revenue_status, sort=sort,
    )
    query = build_games_query(filters)
    rows = (
        await db.execute(query.stmt.options(*_LOAD_OPTIONS).limit(EXPORT_ROW_CAP))
    ).all()
    items = [row_to_list_item(row) for row in rows]

    payload, filename = export_bytes(items, format)

    # Best-effort server-side copy into exports/ (mounted in Docker).
    try:
        exports_dir = Path(get_settings().exports_dir)
        exports_dir.mkdir(parents=True, exist_ok=True)
        (exports_dir / filename).write_bytes(payload)
    except OSError:
        pass

    return Response(
        content=payload,
        media_type=MEDIA_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
