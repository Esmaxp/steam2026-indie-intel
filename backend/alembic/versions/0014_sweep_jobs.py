"""sweep_jobs — on-demand collector runs triggered from the admin UI.

The three collectors (disclosures, followers, rank) already run for hours and
are already resumable. This table gives them a persisted status so a browser
can start one, close the tab, and come back to live progress — and so an
interrupted run is visibly interrupted rather than silently gone.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "sweep_jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        # Which collectors this run covers, in execution order.
        sa.Column("kinds", postgresql.ARRAY(sa.Text), nullable=False),
        # Release-date window limiting WHICH GAMES are scanned. Both nullable
        # = the whole catalogue. The rank sweep ignores these: it reads a
        # single global chart that Valve orders itself.
        sa.Column("release_from", sa.Date),
        sa.Column("release_to", sa.Date),
        sa.Column("limit_per_kind", sa.Integer),
        sa.Column("status", sa.Text, nullable=False, server_default="queued"),
        # Set by the API; the runner checks it between games so a long sweep
        # can be stopped without killing the backend.
        sa.Column("cancel_requested", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        # {"followers": {"total": n, "processed": n, "written": n, ...}, ...}
        sa.Column("progress", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error", sa.Text),
        sa.CheckConstraint(
            "status in ('queued','running','done','failed','cancelled','interrupted')",
            name="status",
        ),
    )
    op.create_index("ix_sweep_jobs_created_at", "sweep_jobs", ["created_at"])

    # A backend restart kills any in-flight run. Mark the survivors on the way
    # in so the UI never shows a job as "running" when nothing is.
    op.execute(
        "UPDATE sweep_jobs SET status = 'interrupted' WHERE status IN ('queued','running')"
    )


def downgrade() -> None:
    op.drop_index("ix_sweep_jobs_created_at", table_name="sweep_jobs")
    op.drop_table("sweep_jobs")
