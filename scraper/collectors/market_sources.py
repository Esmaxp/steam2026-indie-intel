"""Fetch/parse helpers for public market data sources (Phase 4).

Sources and what they legitimately provide:

- Steam appreviews API  — review counts and score (authoritative, Confirmed)
- SteamCharts           — concurrent player stats (public aggregator)
- Steam News API        — Next Fest participation mentions (Confirmed via link)
- Gamalytic public API  — wishlist / sales / revenue ESTIMATES (never facts)

Anything a source does not provide stays None — values are never derived
or invented.
"""

import logging
import os
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from scraper.common.http import SteamClient

logger = logging.getLogger(__name__)

REVIEWS_URL = "https://store.steampowered.com/appreviews/{appid}"
STEAMCHARTS_URL = "https://steamcharts.com/app/{appid}"
NEWS_URL = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
GAMALYTIC_URL = "https://api.gamalytic.com/game/{appid}"

_NEXT_FEST_RE = re.compile(r"next\s*fest", re.I)


# --- Steam reviews ---------------------------------------------------------

@dataclass(frozen=True)
class ReviewSummary:
    positive: int
    negative: int
    total: int
    review_score: int | None
    review_score_desc: str | None

    @property
    def positive_pct(self) -> float | None:
        if self.total <= 0:
            return None
        return round(self.positive / self.total * 100, 2)


async def fetch_review_summary(client: SteamClient, appid: int) -> ReviewSummary | None:
    data = await client.get_json(
        REVIEWS_URL.format(appid=appid),
        params={"json": 1, "num_per_page": 0, "language": "all", "purchase_type": "all"},
    )
    if data.get("success") != 1:
        return None
    summary = data.get("query_summary") or {}
    return ReviewSummary(
        positive=int(summary.get("total_positive") or 0),
        negative=int(summary.get("total_negative") or 0),
        total=int(summary.get("total_reviews") or 0),
        review_score=summary.get("review_score"),
        review_score_desc=summary.get("review_score_desc"),
    )


# --- SteamCharts CCU -------------------------------------------------------

@dataclass(frozen=True)
class CcuStats:
    peak_all_time: int | None
    avg_recent: float | None  # "Last 30 Days" average concurrent players


def parse_steamcharts(html: str) -> CcuStats:
    soup = BeautifulSoup(html, "html.parser")

    peak_all_time = None
    for stat in soup.select("div.app-stat"):
        label = stat.get_text(" ", strip=True).lower()
        num_el = stat.select_one("span.num")
        if num_el and "all-time peak" in label:
            try:
                peak_all_time = int(num_el.get_text(strip=True).replace(",", ""))
            except ValueError:
                pass

    avg_recent = None
    first_row = soup.select_one("table.common-table tbody tr")
    if first_row:
        cells = [td.get_text(strip=True) for td in first_row.select("td")]
        if len(cells) >= 2:
            try:
                avg_recent = float(cells[1].replace(",", ""))
            except ValueError:
                pass

    return CcuStats(peak_all_time=peak_all_time, avg_recent=avg_recent)


async def fetch_ccu_stats(client: SteamClient, appid: int) -> CcuStats:
    """404 (no chart yet) and parse misses simply mean unknown."""
    html = await client.get_text(STEAMCHARTS_URL.format(appid=appid))
    return parse_steamcharts(html)


# --- Steam News → Next Fest ------------------------------------------------

@dataclass(frozen=True)
class NextFestMention:
    title: str
    url: str
    date_epoch: int


def find_next_fest_mentions(news_items: list[dict]) -> list[NextFestMention]:
    mentions = []
    for item in news_items:
        corpus = f"{item.get('title', '')}\n{item.get('contents', '')}"
        if _NEXT_FEST_RE.search(corpus):
            mentions.append(
                NextFestMention(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    date_epoch=int(item.get("date") or 0),
                )
            )
    return mentions


async def fetch_next_fest_mentions(client: SteamClient, appid: int) -> list[NextFestMention]:
    data = await client.get_json(
        NEWS_URL, params={"appid": appid, "count": 100, "maxlength": 0, "format": "json"}
    )
    items = (data.get("appnews") or {}).get("newsitems") or []
    return find_next_fest_mentions(items)


# --- Gamalytic estimates ---------------------------------------------------

@dataclass(frozen=True)
class GamalyticEstimates:
    wishlists: int | None = None
    copies_sold: int | None = None
    revenue_usd: float | None = None
    owners: int | None = None
    followers: int | None = None
    source_url: str = ""
    raw_keys: list[str] = field(default_factory=list)


def _first_number(data: dict, keys: tuple[str, ...]) -> float | None:
    """Defensive extraction: the public API's field names are not contractual."""
    for key in keys:
        value = data.get(key)
        if isinstance(value, (int, float)) and value >= 0:
            return value
    return None


def extract_gamalytic(data: dict, appid: int) -> GamalyticEstimates:
    wishlists = _first_number(data, ("wishlists", "wishlistCount", "wishlist"))
    copies = _first_number(data, ("copiesSold", "sales", "unitsSold"))
    revenue = _first_number(data, ("revenue", "totalRevenue", "estimatedRevenue"))
    owners = _first_number(data, ("owners",))
    followers = _first_number(data, ("followers",))
    return GamalyticEstimates(
        wishlists=int(wishlists) if wishlists is not None else None,
        copies_sold=int(copies) if copies is not None else None,
        revenue_usd=float(revenue) if revenue is not None else None,
        owners=int(owners) if owners is not None else None,
        followers=int(followers) if followers is not None else None,
        source_url=f"https://gamalytic.com/game/{appid}",
        raw_keys=sorted(data.keys()),
    )


async def fetch_gamalytic(client: SteamClient, appid: int) -> GamalyticEstimates | None:
    """Estimates — recorded strictly as status=estimated with source.

    As of August 2026 the Gamalytic API requires an API key (paid plans).
    Set GAMALYTIC_API_KEY to enable this source; without it, requests 403
    and wishlist/revenue honestly stay Unknown."""
    params = None
    api_key = os.environ.get("GAMALYTIC_API_KEY", "").strip()
    if api_key:
        params = {"api_key": api_key}
    data = await client.get_json(GAMALYTIC_URL.format(appid=appid), params=params)
    if not isinstance(data, dict) or data.get("error"):
        return None
    return extract_gamalytic(data, appid)
