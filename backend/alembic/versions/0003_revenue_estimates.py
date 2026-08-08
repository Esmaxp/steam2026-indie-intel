"""Multi-source revenue estimates + 'conflicting' data status.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-08

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

data_status = postgresql.ENUM(name="data_status", create_type=False)

NOW = sa.text("now()")


def upgrade() -> None:
    # PostgreSQL 12+ allows ADD VALUE inside a transaction.
    op.execute("ALTER TYPE data_status ADD VALUE IF NOT EXISTS 'conflicting'")

    op.create_table(
        "revenue_estimates",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "appid",
            sa.BigInteger,
            sa.ForeignKey("games.appid", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_name", sa.Text, nullable=False),
        sa.Column("status", data_status, nullable=False, server_default="estimated"),
        sa.Column("revenue_usd", sa.Numeric(14, 2)),
        sa.Column("estimated_sales", sa.BigInteger),
        sa.Column("owners_min", sa.BigInteger),
        sa.Column("owners_max", sa.BigInteger),
        sa.Column("wishlist_count", sa.BigInteger),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_revenue_estimates_appid", "revenue_estimates", ["appid"])
    op.create_index(
        "ix_revenue_estimates_appid_source", "revenue_estimates", ["appid", "source_name"]
    )


def downgrade() -> None:
    op.drop_table("revenue_estimates")
    # Enum values cannot be removed in PostgreSQL; 'conflicting' stays.
