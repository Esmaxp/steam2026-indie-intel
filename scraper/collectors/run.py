"""CLI entrypoint: python -m scraper.collectors.run [--limit N | --appid X]"""

import argparse
import asyncio

from scraper.common.logging import setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect full Steam store data (Phase 3)")
    parser.add_argument(
        "--limit", type=int, default=200,
        help="how many queued games to process this run (resumes automatically)",
    )
    parser.add_argument("--appid", type=int, default=None, help="process a single AppID")
    args = parser.parse_args()

    logger = setup_logging("collector")

    from scraper.collectors.store_data import run_store_collector

    summary = asyncio.run(run_store_collector(limit=args.limit, only_appid=args.appid))
    logger.info("Summary: %s", summary)


if __name__ == "__main__":
    main()
