"""Where a disclosures sweep should begin its walk.

The follower collector resumes for free: select_stale() skips anything with a
fresh snapshot, so re-running it simply continues. The disclosure harvester
cannot do that — it writes rows only for the ~5% of games that announced a
wishlist figure, so "already scanned" leaves no trace in the database for the
other 95%. Its position is the appid it had reached, and nothing else records
that.

Without this column a re-run from the admin UI would restart the walk at appid
0. Ingestion is idempotent so nothing would break, but it would spend hours
re-reading news it has already read.

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NULL means "from the beginning" — a fresh sweep, not a continuation.
    op.add_column("sweep_jobs", sa.Column("start_appid", sa.Integer))


def downgrade() -> None:
    op.drop_column("sweep_jobs", "start_appid")
