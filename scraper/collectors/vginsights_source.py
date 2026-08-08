"""VG Insights public game pages — revenue/sales estimates (cross-check source).

Reality check (verified live, Aug 2026): vginsights.com redirects to
app.sensortower.com/vgi/... and the game page is an Angular SPA shell — the
figures load behind authentication. The parser below therefore returns None
on today's live pages and the SourceBreaker disables the source for the run
(values honestly stay Unknown). The parsing is kept as a pure, fixture-tested
function against VGI's server-rendered structure so a future change (or a
rendering proxy) starts yielding data without code changes elsewhere.

Rules followed: robots.txt is checked before scraping; no key exists to
configure; ≤2 fetch attempts (no SteamCharts-style retry burn)."""

import logging
import re
import urllib.robotparser
from dataclasses import dataclass

from bs4 import BeautifulSoup

from scraper.common.http import SteamClient

logger = logging.getLogger(__name__)

VGINSIGHTS_GAME_URL = "https://vginsights.com/game/{appid}"
VGINSIGHTS_ROBOTS_URL = "https://vginsights.com/robots.txt"

_LABELS_REVENUE = re.compile(r"^\s*(total\s+)?revenue\s*$", re.I)
_LABELS_UNITS = re.compile(r"^\s*(units|copies)\s+sold\s*$", re.I)
_LABELS_OWNERS = re.compile(r"^\s*owners\s*$", re.I)

_NUMBER_RE = re.compile(r"\$?\s*([\d.,]+)\s*([kmb])?", re.I)


@dataclass(frozen=True)
class VGInsightsEstimates:
    revenue_usd: float | None
    copies_sold: int | None
    owners_min: int | None
    owners_max: int | None
    source_url: str


def parse_compact_number(raw: str | None) -> float | None:
    """"$1.2m" → 1_200_000.0; "85.3k" → 85_300.0; "1,234" → 1234.0."""
    if not raw:
        return None
    match = _NUMBER_RE.search(raw)
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    multiplier = {"k": 1e3, "m": 1e6, "b": 1e9}.get((match.group(2) or "").lower(), 1)
    return value * multiplier


def _value_near(label_node) -> str | None:
    """Nearest numeric-looking text after a stat label element."""
    parent = label_node.parent
    if parent is None:
        return None
    for sibling in parent.find_next_siblings():
        text = sibling.get_text(" ", strip=True)
        if text and _NUMBER_RE.search(text):
            return text
    container = parent.parent
    if container is not None:
        text = container.get_text(" ", strip=True)
        stripped = text.replace(label_node.strip(), "", 1)
        if _NUMBER_RE.search(stripped):
            return stripped
    return None


def _find_stat(soup: BeautifulSoup, label_re: re.Pattern) -> str | None:
    for node in soup.find_all(string=label_re):
        value = _value_near(node)
        if value:
            return value
    return None


def parse_vginsights_html(html: str, appid: int) -> VGInsightsEstimates | None:
    """Pure parser (fixture-tested). None when the expected stats are absent —
    e.g. today's SPA shell, a 'game not found' page, or a structure change."""
    soup = BeautifulSoup(html, "html.parser")

    revenue = parse_compact_number(_find_stat(soup, _LABELS_REVENUE))
    units = parse_compact_number(_find_stat(soup, _LABELS_UNITS))
    owners_min = owners_max = None
    owners_text = _find_stat(soup, _LABELS_OWNERS)
    if owners_text:
        parts = re.split(r"\.\.|–|-", owners_text)
        if len(parts) == 2:
            low = parse_compact_number(parts[0])
            high = parse_compact_number(parts[1])
            if low is not None and high is not None:
                owners_min, owners_max = int(low), int(high)

    if revenue is None and units is None and owners_min is None:
        return None
    return VGInsightsEstimates(
        revenue_usd=revenue,
        copies_sold=int(units) if units is not None else None,
        owners_min=owners_min,
        owners_max=owners_max,
        source_url=VGINSIGHTS_GAME_URL.format(appid=appid),
    )


async def robots_allows_games(client: SteamClient) -> bool:
    """Checked once per run before any page fetch."""
    try:
        robots_txt = await client.get_text(VGINSIGHTS_ROBOTS_URL)
    except Exception as exc:
        logger.warning("VG Insights robots.txt unreachable (%s) — not scraping", exc)
        return False
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(robots_txt.splitlines())
    return parser.can_fetch("*", VGINSIGHTS_GAME_URL.format(appid=1))


async def fetch_vginsights(client: SteamClient, appid: int) -> VGInsightsEstimates | None:
    html = await client.get_text(VGINSIGHTS_GAME_URL.format(appid=appid))
    return parse_vginsights_html(html, appid)
