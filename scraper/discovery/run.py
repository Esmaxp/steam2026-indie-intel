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
    parser.add_argument(
        "--appid",
        type=str,
        default=None,
        help="targeted mode: check specific AppID(s) (comma-separated) without "
        "a full scan — for freshly listed games the search passes missed",
    )
    parser.add_argument(
        "--include-untagged",
        action="store_true",
        help="also admit games WITHOUT the Steam Indie genre/tag when they are "
        "self-published or on a known boutique indie label. With --mode search "
        "this scans ALL 2026 games via the store search (fast, recommended); "
        "with --mode applist it widens the exhaustive GetAppList scan. "
        "Off by default — scope-widening is opt-in.",
    )
    args = parser.parse_args()

    logger = setup_logging("discovery")

    from scraper.discovery.service import (
        run_applist_discovery,
        run_search_discovery,
        run_targeted_discovery,
        run_untagged_search_discovery,
    )

    if args.appid:
        appids = [int(a) for a in args.appid.split(",") if a.strip()]
        summary = asyncio.run(run_targeted_discovery(appids))
    elif args.mode == "search" and args.include_untagged:
        summary = asyncio.run(run_untagged_search_discovery(max_pages=args.max_pages))
    elif args.mode == "search":
        summary = asyncio.run(run_search_discovery(max_pages=args.max_pages))
    else:
        summary = asyncio.run(
            run_applist_discovery(limit=args.limit, include_untagged=args.include_untagged)
        )
    logger.info("Summary: %s", summary)


if __name__ == "__main__":
    main()
