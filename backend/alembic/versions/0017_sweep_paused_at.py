"""When a sweep was paused.

`paused` says a run is holding position; this says since when. Needed because
the admin list orders paused runs by how recently they were parked, and a
boolean cannot express that.

Stamped when the pause is requested rather than when the worker confirms it:
the operator's question is "which did I pause last", and the worker may take
up to a request interval to notice. Cleared on resume and on finish, so it
always means "paused since", never "was paused once".

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sweep_jobs", sa.Column("paused_at", sa.DateTime(timezone=True)))
    # Rows already parked when this shipped have no recorded pause time. The
    # heartbeat is the closest honest stand-in: a paused worker keeps stamping
    # it, so it is at worst a few seconds late.
    op.execute("UPDATE sweep_jobs SET paused_at = heartbeat_at WHERE paused")


def downgrade() -> None:
    op.drop_column("sweep_jobs", "paused_at")
