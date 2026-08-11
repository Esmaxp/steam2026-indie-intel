"""Auto-detected channel candidates: submission provenance + scan bookkeeping.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-11

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NOW = sa.text("now()")


def upgrade() -> None:
    # Who proposed the channels: developer_submitted (form) or auto_detected
    # (website scanner). Both land in the same review queue.
    op.add_column(
        "channel_submissions",
        sa.Column("source", sa.Text, nullable=False, server_default="developer_submitted"),
    )
    # For auto-detected rows: the official website the links were found on,
    # shown in the admin view for a quick sanity check.
    op.add_column("channel_submissions", sa.Column("found_on", sa.Text))

    # One row per scanned game website — makes the scanner resumable and
    # prevents re-scanning within the skip window.
    op.create_table(
        "website_scans",
        sa.Column(
            "appid",
            sa.BigInteger,
            sa.ForeignKey("games.appid", ondelete="CASCADE"),
            primary_key=True,
            autoincrement=False,
        ),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        # found | none | fetch_error | robots_disallowed | not_html
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("links_found", sa.Integer, nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("website_scans")
    op.drop_column("channel_submissions", "found_on")
    op.drop_column("channel_submissions", "source")
