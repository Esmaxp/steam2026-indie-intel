"""Steam Search discovery source.

Uses the store search endpoint (infinite-scroll JSON) filtered to games
carrying the Indie tag. Efficient: release-date-sorted paging finds 2026
releases without scanning the entire Steam catalog.
"""

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

from bs4 import BeautifulSoup

from scraper.common.http import SteamClient

logger = logging.getLogger(__name__)

SEARCH_URL = "https://store.steampowered.com/search/results/"
INDIE_TAG_ID = 492      # Steam store tag "Indie"
CATEGORY_GAMES = 998    # Steam search category1 for games
PAGE_SIZE = 50

BASE_PARAMS = {
    "query": "",
    "count": PAGE_SIZE,
    "dynamic_data": "",
    "force_infinite": 1,
    "infinite": 1,
    "ndl": 1,
    "category1": CATEGORY_GAMES,
    "tags": INDIE_TAG_ID,
    "cc": "us",
    "l": "english",
}


@dataclass(frozen=True)
class SearchRow:
    appid: int
    name: str
    release_text: str


def parse_results_html(html: str) -> list[SearchRow]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[SearchRow] = []
    for anchor in soup.select("a.search_result_row"):
        raw_appid = anchor.get("data-ds-appid")
        if not raw_appid:
            continue  # bundles / packages have no single appid
        try:
            appid = int(str(raw_appid).split(",")[0])
        except ValueError:
            continue
        title_el = anchor.select_one("span.title")
        released_el = anchor.select_one(".search_released")
        if title_el is None:
            continue
        rows.append(
            SearchRow(
                appid=appid,
                name=title_el.get_text(strip=True),
                release_text=released_el.get_text(strip=True) if released_el else "",
            )
        )
    return rows


async def iter_search_pages(
    client: SteamClient,
    extra_params: dict,
    max_pages: int,
) -> AsyncIterator[tuple[list[SearchRow], int]]:
    """Yield (rows, total_count) per page until exhausted or max_pages."""
    start = 0
    for _ in range(max_pages):
        params = {**BASE_PARAMS, **extra_params, "start": start}
        data = await client.get_json(SEARCH_URL, params=params)
        if not data.get("success"):
            logger.warning("Search page start=%s returned success=%s", start, data.get("success"))
            return
        rows = parse_results_html(data.get("results_html", ""))
        total = int(data.get("total_count", 0))
        if not rows:
            return
        yield rows, total
        start += PAGE_SIZE
        if start >= total:
            return
