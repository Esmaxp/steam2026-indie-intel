"""Two independent axes: production effort and market traction.

Replaces the single effort_tier/effort_signals pair added in 0015 with the full
design: a 0-100 score and a class per axis, the four-way label, and the
confidence to read it with. Raw inputs (prices, media rows, review counts,
rank entries) are untouched — the scoring methodology has to stay re-runnable
against them, which is why nothing here stores a derived value that cannot be
recomputed.

`traction_status` records *why* a traction score is missing: a game released
three weeks ago has not failed, and neither has one whose store page has not
been read yet. Both are INSUFFICIENT_DATA rather than a low score.

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("games", "effort_tier", new_column_name="effort_class")
    op.add_column("games", sa.Column("effort_score", sa.Integer, nullable=True))

    op.add_column("games", sa.Column("traction_score", sa.Integer, nullable=True))
    op.add_column(
        "games",
        sa.Column("traction_class", sa.Text, nullable=False, server_default="unknown"),
    )
    op.add_column(
        "games",
        sa.Column(
            "traction_status", sa.Text, nullable=False, server_default="insufficient_data_no_signals"
        ),
    )
    op.add_column(
        "games",
        sa.Column("traction_signals", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "games",
        sa.Column(
            "classification", sa.Text, nullable=False, server_default="INSUFFICIENT_DATA"
        ),
    )
    op.add_column(
        "games",
        sa.Column("classification_confidence", sa.Text, nullable=False, server_default="low"),
    )
    op.execute("ALTER INDEX ix_games_effort_tier RENAME TO ix_games_effort_class")
    op.create_index("ix_games_classification", "games", ["classification"])


def downgrade() -> None:
    op.drop_index("ix_games_classification", table_name="games")
    op.execute("ALTER INDEX ix_games_effort_class RENAME TO ix_games_effort_tier")
    for column in (
        "classification_confidence",
        "classification",
        "traction_signals",
        "traction_status",
        "traction_class",
        "traction_score",
        "effort_score",
    ):
        op.drop_column("games", column)
    op.alter_column("games", "effort_class", new_column_name="effort_tier")
