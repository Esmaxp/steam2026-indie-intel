"""First-party demand signals: Valve wishlist rank, follower snapshots, disclosure provenance.

Steam publishes no wishlist counts, so this project measures demand from what
Valve does publish: the Top-Wishlists ORDINAL and community-hub follower
counts. Neither is a wishlist count and neither is stored as one.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-12

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NOW = sa.text("now()")


def upgrade() -> None:
    # --- sweep header -------------------------------------------------------
    # A truncated sweep must never be able to masquerade as a complete one.
    # Without this row, a 429-aborted run makes every game below the cut-off
    # read "Not ranked" and manufactures an enormous fake rank delta.
    op.create_table(
        "wishlist_rank_sweeps",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        # Store listings are region-scoped: an unpinned cc returns a different
        # ordering entirely, so the region is part of the observation.
        sa.Column("cc", sa.Text, nullable=False, server_default="us"),
        sa.Column("total_count", sa.Integer),  # the endpoint's echoed total
        sa.Column("rows_ingested", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.Text, nullable=False, server_default="partial"),
        sa.Column("source_url", sa.Text),
        sa.Column("notes", sa.Text),
        # Bare suffix: NAMING_CONVENTION renders this as
        # ck_wishlist_rank_sweeps_status. Passing the full name would double
        # the prefix.
        sa.CheckConstraint("status in ('complete','partial','failed')", name="status"),
    )

    # --- ranked entries -----------------------------------------------------
    # NOTE: appid deliberately carries NO foreign key to games.appid, which is
    # a departure from every other table here. The chart is a global ~5.2k-row
    # list covering all of Steam while our catalogue is indie-only, so an FK
    # would discard most rows and make it impossible to backfill rank history
    # for a game discovered later. Consumers INNER JOIN to games instead.
    #
    # This table must never feed discovery: the listing contains released,
    # DLC and hardware rows, and admitting from it would poison the catalogue.
    op.create_table(
        "wishlist_rank_entries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "sweep_id",
            sa.Integer,
            sa.ForeignKey("wishlist_rank_sweeps.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("appid", sa.BigInteger, nullable=False),
        sa.Column("rank", sa.Integer, nullable=False),
        sa.Column("name", sa.Text),
        sa.UniqueConstraint("sweep_id", "appid", name="uq_wishlist_rank_entries_sweep_appid"),
    )
    op.create_index(
        "ix_wishlist_rank_entries_appid_sweep", "wishlist_rank_entries", ["appid", "sweep_id"]
    )

    # --- follower snapshots -------------------------------------------------
    # Deliberately NOT steam_stats.followers, even though that column exists.
    # latest_stats_sq() is DISTINCT ON (appid) ORDER BY captured_at DESC, so a
    # follower-only row written on the daily follower cadence would become
    # "the latest stats row" and blank total_reviews / positive_pct / peak_ccu
    # / avg_ccu in the list API. Followers run on a different cadence (daily,
    # upcoming games) than reviews and CCU (market queue, released games), so
    # they cannot share a DISTINCT-ON table.
    op.create_table(
        "follower_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "appid",
            sa.BigInteger,
            sa.ForeignKey("games.appid", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("followers", sa.Integer, nullable=False),
        sa.Column("source_name", sa.Text),
        sa.Column("source_url", sa.Text),
    )
    op.create_index(
        "ix_follower_snapshots_appid_captured_at",
        "follower_snapshots",
        ["appid", "captured_at"],
    )

    # --- disclosure provenance on wishlist_records --------------------------
    # Most developer milestone posts are round-number lower bounds ("over
    # 100,000 wishlists"), so recording '=' for them would overstate what was
    # actually disclosed. comparator is load-bearing, not decorative.
    op.add_column(
        "wishlist_records",
        sa.Column("comparator", sa.Text, nullable=False, server_default=sa.text("'='")),
    )
    # The announcement's own UTC date. recorded_at stays as ingestion time —
    # for a disclosure those are different things and only one is the
    # observation date.
    op.add_column("wishlist_records", sa.Column("disclosed_on", sa.Date))
    # Bare suffix — NAMING_CONVENTION prefixes it (ck_wishlist_records_comparator).
    op.create_check_constraint("comparator", "wishlist_records", "comparator in ('=', '>=')")
    # Makes the disclosure harvester re-runnable: the same figure from the
    # same announcement URL cannot be ingested twice. Partial, because
    # collector-written rows share a source_url per source and would collide.
    op.create_index(
        "uq_wishlist_records_disclosure",
        "wishlist_records",
        ["appid", "source_url", "wishlist_count"],
        unique=True,
        postgresql_where=sa.text("source_url IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_wishlist_records_disclosure", table_name="wishlist_records")
    # Bare suffix here too — drop_constraint applies NAMING_CONVENTION exactly
    # as create does, so passing the rendered name would double the prefix.
    op.drop_constraint("comparator", "wishlist_records", type_="check")
    op.drop_column("wishlist_records", "disclosed_on")
    op.drop_column("wishlist_records", "comparator")

    op.drop_index("ix_follower_snapshots_appid_captured_at", table_name="follower_snapshots")
    op.drop_table("follower_snapshots")

    op.drop_index("ix_wishlist_rank_entries_appid_sweep", table_name="wishlist_rank_entries")
    op.drop_table("wishlist_rank_entries")

    op.drop_table("wishlist_rank_sweeps")
