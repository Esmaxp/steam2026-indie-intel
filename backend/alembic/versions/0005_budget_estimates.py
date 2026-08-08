"""Budget estimates (auditable heuristics) + disclosed team inputs.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-08

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "budget_estimates",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "appid",
            sa.BigInteger,
            sa.ForeignKey("games.appid", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("method", sa.Text, nullable=False),  # team_cost | revenue_ratio
        sa.Column("budget_min_usd", sa.Numeric(14, 2)),
        sa.Column("budget_max_usd", sa.Numeric(14, 2)),
        sa.Column("formula", sa.Text, nullable=False),
        sa.Column("inputs", postgresql.JSONB, nullable=False),
        sa.Column("source_name", sa.Text),
        sa.Column("source_url", sa.Text),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_budget_estimates_appid", "budget_estimates", ["appid"])

    # Inputs for the team-cost method — only ever filled from disclosed,
    # human-verified sources via the disclosed_numbers CLI.
    op.add_column("marketing_info", sa.Column("team_size", sa.Integer))
    op.add_column("marketing_info", sa.Column("team_region", sa.Text))
    op.add_column("marketing_info", sa.Column("dev_duration_months", sa.Integer))


def downgrade() -> None:
    op.drop_column("marketing_info", "dev_duration_months")
    op.drop_column("marketing_info", "team_region")
    op.drop_column("marketing_info", "team_size")
    op.drop_table("budget_estimates")
