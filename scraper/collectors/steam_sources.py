"""Fetch helpers for the per-game Steam sources used by the store collector."""

import datetime
import json
import logging
import re

from scraper.common.http import SteamClient
from scraper.discovery.release_date import parse_release

logger = logging.getLogger(__name__)

APP_DETAILS_URL = "https://store.steampowered.com/api/appdetails"
STORE_PAGE_URL = "https://store.steampowered.com/app/{appid}/"
DECK_REPORT_URL = "https://store.steampowered.com/saleaction/ajaxgetdeckappcompatibilityreport"

# Bypass the age gate on mature store pages.
AGE_GATE_COOKIES = {
    "birthtime": "568022401",
    "lastagecheckage": "1-January-1988",
    "wants_mature_content": "1",
}

_TAG_MODAL_RE = re.compile(r"InitAppTagModal\(\s*\d+\s*,\s*(\[.*?\])\s*,", re.S)


async def fetch_appdetails(client: SteamClient, appid: int) -> dict | None:
    data = await client.get_json(
        APP_DETAILS_URL, params={"appids": appid, "cc": "us", "l": "english"}
    )
    entry = data.get(str(appid)) or {}
    if not entry.get("success") or not entry.get("data"):
        return None
    return entry["data"]


async def fetch_store_page_tags(client: SteamClient, appid: int) -> list[tuple[str, int]]:
    """User-defined tags with vote counts, parsed from the store page JS blob."""
    html = await client.get_text(STORE_PAGE_URL.format(appid=appid), params={"l": "english"})
    match = _TAG_MODAL_RE.search(html)
    if not match:
        logger.debug("No tag modal found for appid %s", appid)
        return []
    try:
        raw = json.loads(match.group(1))
    except json.JSONDecodeError:
        logger.warning("Tag JSON parse failed for appid %s", appid)
        return []
    tags = [(t.get("name", ""), int(t.get("count", 0))) for t in raw if t.get("name")]
    tags.sort(key=lambda item: item[1], reverse=True)
    return tags


async def fetch_deck_category(client: SteamClient, appid: int) -> int:
    """Steam Deck compatibility: 0 unknown, 1 unsupported, 2 playable, 3 verified."""
    data = await client.get_json(DECK_REPORT_URL, params={"nAppID": appid, "l": "english"})
    if data.get("success") != 1:
        return 0
    results = data.get("results") or {}
    return int(results.get("resolved_category", 0))


async def fetch_demo_release_date(
    client: SteamClient, demo_appid: int
) -> datetime.date | None:
    """A demo is its own Steam app; its appdetails carry the demo release date."""
    details = await fetch_appdetails(client, demo_appid)
    if not details:
        return None
    release_info = details.get("release_date") or {}
    return parse_release(release_info.get("date")).date


def parse_supported_languages(raw_html: str | None) -> list[str]:
    """appdetails delivers languages as an HTML fragment with footnotes."""
    if not raw_html:
        return []
    text = re.split(r"<br\s*/?>", raw_html, flags=re.I)[0]
    text = re.sub(r"<[^>]+>", "", text).replace("*", "")
    return [part.strip() for part in text.split(",") if part.strip()]
