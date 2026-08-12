"""CLI entrypoint: python -m scraper.collectors.run_rank_sweep [--dry-run]

Sweeps Valve's Top-Wishlists chart and records each game's ORDINAL position.
Roughly 53 requests at 3s spacing, so about 3 minutes wall clock.

Usage:
    python -m scraper.collectors.run_rank_sweep [--dry-run]
    docker compose run --rm rank_sweep
"""

import argparse
import asyncio

from scraper.common.logging import setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sweep Valve's Top-Wishlists ordinal ranking (first-party, no API key)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and validate, but write nothing to the database",
    )
    args = parser.parse_args()

    logger = setup_logging("rank_sweep")

    from scraper.collectors.wishlist_rank import run_rank_sweep

    summary = asyncio.run(run_rank_sweep(dry_run=args.dry_run))
    logger.info("Summary: %s", summary)


if __name__ == "__main__":
    main()
