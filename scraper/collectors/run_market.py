"""CLI entrypoint: python -m scraper.collectors.run_market [--limit N | --appid X]"""

import argparse
import asyncio

from scraper.common.logging import setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect public market & business data (Phase 4)"
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="max queued games this run; 0 = entire queue (default)",
    )
    parser.add_argument("--appid", type=int, default=None, help="process a single AppID")
    args = parser.parse_args()

    logger = setup_logging("market")

    from scraper.collectors.market_data import run_market_collector

    summary = asyncio.run(run_market_collector(limit=args.limit, only_appid=args.appid))
    logger.info("Summary: %s", summary)


if __name__ == "__main__":
    main()
