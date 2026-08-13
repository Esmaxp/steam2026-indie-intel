"""On-demand collector runs started from the admin UI."""

import datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Collector kinds a job may request. Kept as plain strings rather than a PG
# enum so adding one later is a code change, not an ALTER TYPE migration.
SWEEP_KINDS = ("disclosures", "followers", "rank")

TERMINAL_STATUSES = ("done", "failed", "cancelled", "interrupted")


class SweepJob(Base):
    __tablename__ = "sweep_jobs"
    __table_args__ = (
        CheckConstraint(
            "status in ('queued','running','done','failed','cancelled','interrupted')",
            name="status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kinds: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)

    # Which GAMES to scan, by release date. The rank sweep ignores this — it
    # reads one global chart whose membership Valve decides.
    release_from: Mapped[datetime.date | None] = mapped_column(Date)
    release_to: Mapped[datetime.date | None] = mapped_column(Date)
    limit_per_kind: Mapped[int | None] = mapped_column(Integer)

    status: Mapped[str] = mapped_column(Text, server_default="queued", nullable=False)
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False
    )
    # Distinct from cancel_requested: stop is terminal, pause holds position.
    paused: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    # Last sign of life from the executing process. A CLI batch runs outside
    # the backend, so this is the only way to tell a live job from one whose
    # shell loop was killed.
    heartbeat_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    active_kind: Mapped[str | None] = mapped_column(Text)
    # Which process owns this row: "api" (in the backend) or "cli" (a sweep
    # script). The backend clears only its own on startup.
    runner: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    progress: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
