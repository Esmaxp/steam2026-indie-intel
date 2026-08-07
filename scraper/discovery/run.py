"""CLI entrypoint: python -m scraper.discovery.run [--mode search|applist]"""

import argparse
import asyncio

from scraper.common.logging import setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover Steam 2026 indie games")
    parser.add_argument(
        "--mode",
        choices=["search", "applist"],
        default="search",
        help="search: fast Steam Search discovery (default); "
        "applist: exhaustive resumable GetAppList scan",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="applist mode: how many pending apps to validate this run",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=2000,
        help="search mode: safety cap on pages per pass (2000 pages = 100k rows)",
    )
    args = parser.parse_args()

    logger = setup_logging("discovery")

    from scraper.discovery.service import run_applist_discovery, run_search_discovery

    if args.mode == "search":
        summary = asyncio.run(run_search_discovery(max_pages=args.max_pages))
    else:
        summary = asyncio.run(run_applist_discovery(limit=args.limit))
    logger.info("Summary: %s", summary)


if __name__ == "__main__":
    main()
