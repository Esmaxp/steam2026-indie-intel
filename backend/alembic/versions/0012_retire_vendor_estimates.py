"""Delete third-party vendor estimates; revenue has no first-party source.

This project reports measured signals and developer-disclosed figures only.
Gamalytic, SteamSpy and VG Insights were retired in the collector layer;
this removes the rows they left behind.

DELETE rather than freeze, deliberately: leaving vendor-derived numbers in
place would keep serving them from a product that states it uses no vendors,
and the committed database/seed/full_export.dump would re-seed them into
every fresh clone. The dump is regenerated alongside this migration.

Nothing actionable is lost. Of the 8,380 rows, 0 carry revenue, 0 carry
sales and 0 carry a wishlist figure; 99.8% are the 0-20,000 owners bucket,
and exactly 15 rows hold a narrower band. Revenue was already surfacing as
Unknown for every game.

DOWNGRADE IS A NO-OP AND CANNOT RESTORE THESE ROWS. That mirrors the
one-way UPDATE in 0010_dimension_source.py. Recovery, if ever needed, is
from the pre-migration seed dump in git history (commit 60c32ca).

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

VENDORS = ("steamspy", "gamalytic", "vginsights")


def upgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM revenue_estimates WHERE source_name IN "
            "('steamspy','gamalytic','vginsights')"
        )
    )
    # IS DISTINCT FROM rather than <> so NULL source_name rows are removed
    # too: a summary row with no recorded source cannot be attributed to a
    # developer disclosure, which is the only provenance now permitted here.
    op.execute(
        sa.text("DELETE FROM revenue_records WHERE source_name IS DISTINCT FROM 'disclosed'")
    )


def downgrade() -> None:
    """Intentionally empty — the deleted rows are not recoverable here.

    Downgrading past this revision restores the schema, not the vendor data.
    See the module docstring for the recovery path.
    """
