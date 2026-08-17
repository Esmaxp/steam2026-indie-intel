"""Signals that separate a serious attempt from a hobby upload.

Steam prints two things on the store page that appdetails omits: whether a
game's profile features are still restricted ("Steam is learning about this
game"), and whether the developer declared generative-AI content. Both are
recorded here. So are two appdetails fields the collector was discarding: the
list price (the discounted `final` price cannot say how a game is positioned)
and the achievement count.

effort_tier / effort_signals hold the verdict and its reasoning, the same way
budget_estimates stores `inputs` next to its numbers — a tier nobody can audit
is a tier nobody should trust.

NULL means "not looked at yet", not False: every row predates this migration,
and the backfill worker fills them. games.website already uses that tri-state.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("games", sa.Column("list_price_cents", sa.Integer, nullable=True))
    op.add_column("games", sa.Column("achievements_count", sa.Integer, nullable=True))
    op.add_column("games", sa.Column("limited_profile", sa.Boolean, nullable=True))
    op.add_column("games", sa.Column("ai_disclosure", sa.Boolean, nullable=True))
    op.add_column(
        "games",
        sa.Column("effort_tier", sa.Text, nullable=False, server_default="unknown"),
    )
    op.add_column(
        "games",
        sa.Column("effort_signals", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    # The tier is a filter target on a 23k-row table, and 'unknown' will be the
    # majority value until the backfill runs — index it.
    op.create_index("ix_games_effort_tier", "games", ["effort_tier"])


def downgrade() -> None:
    op.drop_index("ix_games_effort_tier", table_name="games")
    for column in (
        "effort_signals",
        "effort_tier",
        "ai_disclosure",
        "limited_profile",
        "achievements_count",
        "list_price_cents",
    ):
        op.drop_column("games", column)
