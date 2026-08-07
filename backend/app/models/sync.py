import datetime

from sqlalchemy import BigInteger, DateTime, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models._types import pg_enum
from app.models.enums import SyncStage, SyncStatus


class SyncState(Base):
    """Scraper resume support: tracks each (appid, stage) pipeline step.

    No FK to games — discovery records state before a game row exists.
    """

    __tablename__ = "sync_states"

    appid: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    stage: Mapped[SyncStage] = mapped_column(pg_enum(SyncStage, "sync_stage"), primary_key=True)
    status: Mapped[SyncStatus] = mapped_column(
        pg_enum(SyncStatus, "sync_status"), default=SyncStatus.PENDING, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
