"""Persist the store legal notice so engine detection stays replayable.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-12

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # _ENGINE_PATTERNS matches mostly against the store's legal notice ("Unreal®
    # Engine, Copyright...", "Made with Unity"), but the collector built that
    # text in memory and dropped it. Since store_data never re-runs for a game
    # once DONE, every future engine-rule improvement would have been invisible
    # to rows collected earlier. Keeping the text makes engine detection
    # replayable offline, the same way stored tags make the classifier
    # replayable (workers/reclassify_classification.py).
    #
    # Rows collected before this migration stay NULL: backfilling means
    # re-fetching appdetails for every game at ~1.5s each. NULL therefore means
    # "not captured", not "the game has no legal notice" (that is the empty
    # string) — the same tri-state games.website already uses.
    op.add_column("games", sa.Column("legal_notice", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("games", "legal_notice")
