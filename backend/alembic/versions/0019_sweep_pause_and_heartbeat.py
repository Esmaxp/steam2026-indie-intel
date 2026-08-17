"""Pause/resume control and a liveness heartbeat for sweeps.

`cancel_requested` already let a run be stopped. Pausing needs its own flag
rather than reusing it, because the two mean different things to the worker:
stop is terminal and finishes the job, pause holds position and expects to
continue.

`heartbeat_at` exists because a sweep can now be driven from the CLI as well
as from the API. The backend runs API-launched sweeps itself and knows when
they die, but a CLI batch is a separate process it cannot observe — without a
heartbeat the UI would show `running` forever after a shell loop was killed.

`runner` records which of the two owns the row. The backend clears its own
live jobs on startup, since a restart kills them by definition; a CLI sweep
survives a backend restart and must not be cleared with them.

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sweep_jobs",
        sa.Column("paused", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    # Last sign of life from whatever process is executing the job.
    op.add_column("sweep_jobs", sa.Column("heartbeat_at", sa.DateTime(timezone=True)))
    # Which collector is executing right now, so the UI can attribute the ETA
    # to a specific step when a job runs several.
    op.add_column("sweep_jobs", sa.Column("active_kind", sa.Text))
    # 'api' = run in the backend process; 'cli' = run by a sweep script.
    op.add_column("sweep_jobs", sa.Column("runner", sa.Text))

    # `paused` is the request; `status='paused'` is the worker confirming it
    # parked. Both exist because they are not simultaneous — a worker checks
    # between games, so there is a gap the UI has to be able to describe.
    # Constraint names here are BARE suffixes: the metadata naming convention
    # expands them to ck_sweep_jobs_<name>.
    op.drop_constraint("status", "sweep_jobs", type_="check")
    op.create_check_constraint(
        "status",
        "sweep_jobs",
        "status in ('queued','running','paused','done','failed','cancelled','interrupted')",
    )


def downgrade() -> None:
    # Rows parked at 'paused' would violate the narrower constraint.
    op.execute("UPDATE sweep_jobs SET status='interrupted' WHERE status='paused'")
    op.drop_constraint("status", "sweep_jobs", type_="check")
    op.create_check_constraint(
        "status",
        "sweep_jobs",
        "status in ('queued','running','done','failed','cancelled','interrupted')",
    )
    op.drop_column("sweep_jobs", "runner")
    op.drop_column("sweep_jobs", "active_kind")
    op.drop_column("sweep_jobs", "heartbeat_at")
    op.drop_column("sweep_jobs", "paused")
