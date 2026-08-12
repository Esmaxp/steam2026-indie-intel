"""Auditability for 2D/3D: where each game's dimension value came from.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-12

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # tag | rule_based | vision_ai | unknown — same auditability pattern as
    # games.discovery_method and channel_submissions.source.
    op.add_column(
        "games",
        sa.Column("dimension_source", sa.Text, nullable=False, server_default="unknown"),
    )
    # Every dimension set before this migration came from the store's own tag.
    op.execute("UPDATE games SET dimension_source = 'tag' WHERE dimension != 'unknown'")


def downgrade() -> None:
    op.drop_column("games", "dimension_source")
