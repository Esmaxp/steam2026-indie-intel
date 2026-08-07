"""Resume support helpers built on the sync_states table."""

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SyncStage, SyncState, SyncStatus


async def mark(
    session: AsyncSession,
    appid: int,
    stage: SyncStage,
    status: SyncStatus,
    error: str | None = None,
) -> None:
    stmt = pg_insert(SyncState).values(
        appid=appid,
        stage=stage,
        status=status,
        attempts=1,
        last_attempt_at=func.now(),
        last_error=error,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[SyncState.appid, SyncState.stage],
        set_={
            "status": status,
            "attempts": SyncState.attempts + 1,
            "last_attempt_at": func.now(),
            "last_error": error,
        },
    )
    await session.execute(stmt)


async def register_pending(session: AsyncSession, appids: list[int], stage: SyncStage) -> int:
    """Insert missing (appid, stage) rows as pending. Existing rows untouched."""
    inserted = 0
    for chunk_start in range(0, len(appids), 5000):
        chunk = appids[chunk_start : chunk_start + 5000]
        stmt = pg_insert(SyncState).values(
            [{"appid": a, "stage": stage, "status": SyncStatus.PENDING} for a in chunk]
        )
        stmt = stmt.on_conflict_do_nothing(
            index_elements=[SyncState.appid, SyncState.stage]
        )
        result = await session.execute(stmt)
        inserted += result.rowcount or 0
    return inserted


async def pending_appids(session: AsyncSession, stage: SyncStage, limit: int) -> list[int]:
    result = await session.execute(
        select(SyncState.appid)
        .where(SyncState.stage == stage, SyncState.status == SyncStatus.PENDING)
        .order_by(SyncState.appid)
        .limit(limit)
    )
    return [row[0] for row in result]
