"""Revenue estimates as ranges, with their formula and inputs attached.

Revenue returns to the schema after 0013 retired the vendor rows, but on
different terms. 0013 deleted third-party point estimates because nobody
could say where they came from; what goes in now is first-party, derived
only from signals this project measures itself (review counts, peak CCU,
follower counts), and it carries its own provenance:

- a RANGE, never a single number — the review-to-sales multiplier varies by
  a factor of two in the source literature, and a point estimate would hide
  that;
- `formula` and `inputs`, the same pattern budget_estimates has used since
  0005, so any figure can be re-derived by hand;
- `method`, so the merge layer can say which signals agreed.

`estimated_sales` and `revenue_usd` keep their meaning and become the MID of
their range — existing readers (revenue_merge, the serializers) keep working
unchanged.

The partial unique index makes the estimator worker re-runnable: one row per
(game, signal), replaced in place. It excludes 'disclosed' because a game can
legitimately have several developer disclosures from different sources, and
those are the one tier this project will not deduplicate automatically.

price_snapshots exists to retire an assumption. Copies are converted to
revenue with an average-selling-price factor that is currently a constant
(0.65 of list) borrowed from the literature. Every appdetails fetch already
carries the list and current price; recording them turns that constant into
something measurable over time. Nothing reads the table yet — it is here so
that the history starts accumulating now rather than when someone needs it.

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-14

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (name, type) for the columns added to revenue_estimates.
_ESTIMATE_COLUMNS = [
    ("method", sa.Text()),
    ("copies_min", sa.BigInteger()),
    ("copies_max", sa.BigInteger()),
    ("revenue_min_usd", sa.Numeric(14, 2)),
    ("revenue_max_usd", sa.Numeric(14, 2)),
    ("net_revenue_usd", sa.Numeric(14, 2)),
    ("net_min_usd", sa.Numeric(14, 2)),
    ("net_max_usd", sa.Numeric(14, 2)),
    ("formula", sa.Text()),
    ("inputs", postgresql.JSONB(astext_type=sa.Text())),
    ("confidence", sa.Text()),
]

_RECORD_COLUMNS = [
    ("gross_min_usd", sa.Numeric(14, 2)),
    ("gross_max_usd", sa.Numeric(14, 2)),
    ("net_min_usd", sa.Numeric(14, 2)),
    ("net_max_usd", sa.Numeric(14, 2)),
    ("sales_min", sa.BigInteger()),
    ("sales_max", sa.BigInteger()),
    ("sources_used", sa.Integer()),
]


def upgrade() -> None:
    for name, type_ in _ESTIMATE_COLUMNS:
        op.add_column("revenue_estimates", sa.Column(name, type_, nullable=True))
    for name, type_ in _RECORD_COLUMNS:
        op.add_column("revenue_records", sa.Column(name, type_, nullable=True))

    op.create_index(
        "uq_revenue_estimates_appid_source",
        "revenue_estimates",
        ["appid", "source_name"],
        unique=True,
        postgresql_where=sa.text("source_name <> 'disclosed'"),
    )

    op.create_table(
        "price_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("appid", sa.BigInteger(), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # All in cents, as Steam reports them. NULL means the storefront did
        # not return a price_overview at all (free games, region-locked
        # pages), which is different from a price of zero.
        sa.Column("list_cents", sa.Integer(), nullable=True),
        sa.Column("current_cents", sa.Integer(), nullable=True),
        sa.Column("discount_pct", sa.Integer(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["appid"], ["games.appid"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_price_snapshots_appid_captured_at",
        "price_snapshots",
        ["appid", "captured_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_price_snapshots_appid_captured_at", table_name="price_snapshots")
    op.drop_table("price_snapshots")
    op.drop_index("uq_revenue_estimates_appid_source", table_name="revenue_estimates")
    for name, _ in reversed(_RECORD_COLUMNS):
        op.drop_column("revenue_records", name)
    for name, _ in reversed(_ESTIMATE_COLUMNS):
        op.drop_column("revenue_estimates", name)
