"""Genre rank: preserve Steam's original appdetails genre order.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-12

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Mirrors game_tags.rank. New collections write Steam's original order;
    # existing rows get a stable (genre_id) order. NOTE: store_data is never
    # re-run once DONE, so existing rows keep this synthetic order permanently
    # unless a game is re-collected via targeted mode (discovery --appid).
    op.add_column(
        "game_genres",
        sa.Column("rank", sa.Integer, nullable=False, server_default="1"),
    )
    op.execute(
        """
        UPDATE game_genres AS gg
        SET rank = numbered.rn
        FROM (
            SELECT appid, genre_id,
                   row_number() OVER (PARTITION BY appid ORDER BY genre_id) AS rn
            FROM game_genres
        ) AS numbered
        WHERE gg.appid = numbered.appid AND gg.genre_id = numbered.genre_id
        """
    )


def downgrade() -> None:
    op.drop_column("game_genres", "rank")
