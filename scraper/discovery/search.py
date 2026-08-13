"""Steam Search discovery source.

Uses the store search endpoint (infinite-scroll JSON) filtered to games
carrying the Indie tag. Efficient: release-date-sorted paging finds 2026
releases without scanning the entire Steam catalog.

HTTP posture for anything that sweeps this endpoint: the store host DOES
rate-limit even at ~3s spacing (measured: one 429 in ~160 requests, no
Retry-After header). SteamClient already maps 429 to RetryableHTTPError with
exponential jitter over 6 attempts — use it as-is. Do NOT lower max_attempts
for a paged sweep: a dropped page does not raise, it silently truncates the
result set, and a short sweep looks identical to a complete one.

`cc` is pinned in BASE_PARAMS deliberately. Store listings are region-scoped,
so an unpinned or differing `cc` returns a materially different result set
(cc=de retained 11/50 positions against cc=us on a sampled page).
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


def parse_search_row(anchor) -> SearchRow | None:
    """One search-result anchor to a SearchRow, or None if it is not a game.

    Keys on data-ds-itemkey ("App_1145360" / "Sub_1686522"), NOT on
    data-ds-appid. A package row carries a comma-separated appid LIST, so
    taking its first element admits a bundled game under the package's title
    and release date — and the same appid can arrive twice from two different
    package rows. Observed live on the popular-wishlist listing:
    Sub_1686522 -> "2054970,2593180,2593190,2593290".

    Every row on the store's search listings carries an itemkey (verified
    50/50 on sampled pages); the data-ds-appid fallback exists only so a
    markup change degrades to skipping rows rather than mis-attributing
    them, which is why a comma there is rejected rather than split.
    """
    itemkey = anchor.get("data-ds-itemkey")
    if itemkey:
        if not str(itemkey).startswith("App_"):
            return None  # Sub_ / Bundle_ rows are not games
        raw_appid = str(itemkey)[len("App_") :]
    else:
        raw_appid = str(anchor.get("data-ds-appid") or "")
        if not raw_appid or "," in raw_appid:
            return None
    try:
        appid = int(raw_appid)
    except ValueError:
        return None

    title_el = anchor.select_one("span.title")
    if title_el is None:
        return None
    released_el = anchor.select_one(".search_released")
    return SearchRow(
        appid=appid,
        name=title_el.get_text(strip=True),
        release_text=released_el.get_text(strip=True) if released_el else "",
    )


def parse_results_html(html: str) -> list[SearchRow]:
    soup = BeautifulSoup(html, "html.parser")
    parsed = (parse_search_row(a) for a in soup.select("a.search_result_row"))
    return [row for row in parsed if row is not None]


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
