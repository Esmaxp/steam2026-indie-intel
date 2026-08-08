"""Indie confidence score + low-quality (mass-publishing) flag.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-08

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

indie_confidence = postgresql.ENUM(
    "high", "medium", "low", name="indie_confidence", create_type=False
)


def upgrade() -> None:
    indie_confidence.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "games",
        sa.Column(
            "indie_confidence", indie_confidence, nullable=False, server_default="medium"
        ),
    )
    op.add_column(
        "games",
        sa.Column(
            "low_quality_signal", sa.Boolean, nullable=False, server_default=sa.text("false")
        ),
    )
    op.create_index("ix_games_indie_confidence", "games", ["indie_confidence"])


def downgrade() -> None:
    op.drop_index("ix_games_indie_confidence", "games")
    op.drop_column("games", "low_quality_signal")
    op.drop_column("games", "indie_confidence")
    indie_confidence.drop(op.get_bind(), checkfirst=True)
