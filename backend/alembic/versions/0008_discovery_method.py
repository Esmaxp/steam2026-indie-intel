"""How each game entered the catalog: indie_tag vs. tag-less publisher signals.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-12

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # indie_tag (default — Steam Indie genre/tag present) |
    # self_published_no_tag | boutique_label_no_tag (opt-in applist fallback).
    # Same auditability idea as channel_submissions.source.
    op.add_column(
        "games",
        sa.Column("discovery_method", sa.Text, nullable=False, server_default="indie_tag"),
    )
    op.create_index("ix_games_discovery_method", "games", ["discovery_method"])


def downgrade() -> None:
    op.drop_index("ix_games_discovery_method", table_name="games")
    op.drop_column("games", "discovery_method")
