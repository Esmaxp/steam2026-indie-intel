"""SteamSpy public API source — owner ranges and player stats.

Endpoint: https://steamspy.com/api.php?request=appdetails&appid={appid}
Free, no API key. SteamSpy publishes *ranges* (e.g. "20,000 .. 50,000"),
never exact numbers — everything from here is status=ESTIMATED.
Rate limit: ~1 req/sec recommended by SteamSpy → collector uses 1.1 s.
"""

import logging
import re
from dataclasses import dataclass

from scraper.common.http import SteamClient

logger = logging.getLogger(__name__)

STEAMSPY_URL = "https://steamspy.com/api.php"

_RANGE_SEP_RE = re.compile(r"\s*\.\.\s*")


@dataclass(frozen=True)
class SteamSpyEstimates:
    owners_min: int | None
    owners_max: int | None
    average_playtime_forever: int | None
    median_playtime_forever: int | None
    ccu: int | None
    source_url: str


def parse_owners_range(raw: str | None) -> tuple[int | None, int | None]:
    """SteamSpy owners string "20,000 .. 50,000" → (20000, 50000).
    Empty or malformed input → (None, None) — never a guess."""
    if not raw or not isinstance(raw, str):
        return None, None
    parts = _RANGE_SEP_RE.split(raw.strip())
    if len(parts) != 2:
        return None, None
    try:
        low = int(parts[0].replace(",", "").strip())
        high = int(parts[1].replace(",", "").strip())
    except ValueError:
        return None, None
    return low, high


def _optional_int(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def extract_steamspy(data: dict, appid: int) -> SteamSpyEstimates | None:
    """Pure extraction from a SteamSpy appdetails payload (testable offline)."""
    if not isinstance(data, dict) or not data.get("appid"):
        return None
    owners_min, owners_max = parse_owners_range(data.get("owners"))
    if owners_min is None and owners_max is None:
        # No owners estimate = nothing useful; SteamSpy has no wishlist data.
        return None
    return SteamSpyEstimates(
        owners_min=owners_min,
        owners_max=owners_max,
        average_playtime_forever=_optional_int(data.get("average_forever")),
        median_playtime_forever=_optional_int(data.get("median_forever")),
        ccu=_optional_int(data.get("ccu")),
        source_url=f"https://steamspy.com/app/{appid}",
    )


async def fetch_steamspy(client: SteamClient, appid: int) -> SteamSpyEstimates | None:
    data = await client.get_json(
        STEAMSPY_URL, params={"request": "appdetails", "appid": appid}
    )
    return extract_steamspy(data, appid)
