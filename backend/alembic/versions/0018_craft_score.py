"""Craft score: production evidence, separated from marketing and pricing.

The effort score added in 0015/0016 answers "was this run like a product?"
and 66 of its 110 positive points are marketing and pricing decisions. That
makes it the wrong instrument for the question the catalogue keeps being
asked — did somebody actually build this — because a developer who shipped
a real game and then never marketed it scores as hobby. 1,421 games sit in
exactly that position today.

craft_score reads only the production signals (screenshots, localisation,
achievements, description, and the two page-quality penalties). None of them
touch price or release status, which incidentally removes a structural
unfairness: on the combined score 0.4% of free games reach 'serious' against
12.7% of paid ones, because free games are exempt from pricing signals but
still measured against a scale that includes them. On craft, released free
games clear the bar 19.5% of the time.

Additive on purpose. effort_score and effort_class keep their meaning and
their values; nothing is recomputed and no existing consumer changes.

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-15

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("games", sa.Column("craft_score", sa.Integer, nullable=True))
    op.add_column(
        "games",
        sa.Column("craft_class", sa.Text, nullable=False, server_default="unknown"),
    )
    # The filter runs in SQL, so the class has to be a column rather than
    # something computed per request.
    op.create_index("ix_games_craft_class", "games", ["craft_class"])


def downgrade() -> None:
    op.drop_index("ix_games_craft_class", table_name="games")
    op.drop_column("games", "craft_class")
    op.drop_column("games", "craft_score")
