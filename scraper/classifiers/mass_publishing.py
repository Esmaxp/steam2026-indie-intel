"""Asset-flip / mass-publishing detection (promt.md Section 1).

A company shipping BURST_COUNT+ games inside any BURST_WINDOW_DAYS window is
flagged: every game of that company gets low_quality_signal=True. Flagged
titles are surfaced separately in the UI — transparency over deletion.

Runs automatically after each store-collector batch; also available as a CLI:
    python -m scraper.classifiers.mass_publishing
"""

import asyncio
import datetime
import logging

import sqlalchemy as sa

from app.db.session import async_session_factory
from app.models import Game, game_developers, game_publishers

logger = logging.getLogger(__name__)

BURST_COUNT = 5
BURST_WINDOW_DAYS = 30


def has_release_burst(
    release_dates: list[datetime.date],
    burst_count: int = BURST_COUNT,
    window_days: int = BURST_WINDOW_DAYS,
) -> bool:
    """True when any sliding window of `window_days` holds `burst_count`+ dates."""
    if len(release_dates) < burst_count:
        return False
    dates = sorted(release_dates)
    for i in range(len(dates) - burst_count + 1):
        if (dates[i + burst_count - 1] - dates[i]).days <= window_days:
            return True
    return False


async def flag_mass_publishing() -> int:
    """Recomputes low_quality_signal for the whole catalog. Returns #flagged."""
    flagged_appids: set[int] = set()
    async with async_session_factory() as db:
        for table, company_col in (
            (game_developers, game_developers.c.developer_id),
            (game_publishers, game_publishers.c.publisher_id),
        ):
            rows = await db.execute(
                sa.select(company_col, Game.appid, Game.release_date)
                .join(Game, Game.appid == table.c.appid)
                .where(Game.release_date.is_not(None))
            )
            by_company: dict[int, list[tuple[int, datetime.date]]] = {}
            for company_id, appid, release_date in rows:
                by_company.setdefault(company_id, []).append((appid, release_date))
            for games in by_company.values():
                if has_release_burst([d for _, d in games]):
                    flagged_appids.update(appid for appid, _ in games)

        # Recompute both directions so games un-flag if data changes.
        await db.execute(
            sa.update(Game)
            .where(Game.appid.in_(flagged_appids) if flagged_appids else sa.false())
            .values(low_quality_signal=True)
        )
        await db.execute(
            sa.update(Game)
            .where(
                sa.not_(Game.appid.in_(flagged_appids)) if flagged_appids else sa.true(),
                Game.low_quality_signal.is_(True),
            )
            .values(low_quality_signal=False)
        )
        await db.commit()

    logger.info("Mass-publishing pass: %d games flagged", len(flagged_appids))
    return len(flagged_appids)


def main() -> None:
    from scraper.common.logging import setup_logging

    setup_logging("mass_publishing")
    asyncio.run(flag_mass_publishing())


if __name__ == "__main__":
    main()
