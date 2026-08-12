"""Steam community-hub follower counts — a MEASURED first-party value.

Followers are the accounts that opted into a game's community hub. Valve
renders this number publicly, so it is exact and citable, and it is the
strongest honest demand signal available for an unreleased game.

What it is NOT: a wishlist count. The wishlist-to-follower ratio spans
roughly 7.5x-30x across titles and does not tighten with scale, so NOTHING
in this codebase may multiply followers into a wishlist estimate. The
number ships as itself or not at all.

Route choice, measured 2026-08-12:
  * PRIMARY `/games/{appid}/members` — the count appears in the paging line
    as "of 444,315 Members". Verified against appid 1422450 (444,315) and
    2109770 (102,942).
  * A game with no community group returns **HTTP 200** with a "Steam
    Community :: Error" page (verified: appid 4553980). Validating on
    status code alone would silently record those games as having no
    followers, so the parser requires the count token and returns None
    otherwise. The caller then writes NOTHING — never a zero.
  * NOT `/memberslistxml/` — it enforces a hard ~60-requests-per-IP quota
    with 120-560s of enforced silence afterwards, which makes it unusable
    for a 5.6k-game sweep. It also serves its 429 as a 24-byte gzipped JSON
    `null`, which an XML parser would swallow into a false "no followers".
"""

import logging
import re
from dataclasses import dataclass

from scraper.common.http import SteamClient

logger = logging.getLogger(__name__)

MEMBERS_URL = "https://steamcommunity.com/games/{appid}/members"

# The rendered paging line, e.g. "1 - 50 of 444,315 Members".
_COUNT_RE = re.compile(r"of\s+([\d,]+)\s+Members", re.I)
# Fallback if Valve rewords the paging line: the same figure is emitted in
# the page's own JS bootstrap on hub pages.
_FALLBACK_RE = re.compile(r'"?member_?count"?\s*[:=]\s*"?(\d+)', re.I)

# Conservative: measured 3.5s x 100 requests with zero 429s, but the upper
# bound was never probed, so this stays an assumption rather than a finding.
# Overridable per-run because a full sweep at 4s is ~6h for 5.6k games.
DEFAULT_MIN_INTERVAL = 4.0


@dataclass(frozen=True)
class FollowerCount:
    appid: int
    followers: int
    source_url: str


def parse_members_count(html: str) -> int | None:
    """Follower count, or None when the page carries no count at all.

    None means "not publicly available" and must never be coerced to 0 —
    a hub-less game and a game with zero followers are different facts.
    """
    match = _COUNT_RE.search(html)
    if match:
        return int(match.group(1).replace(",", ""))
    match = _FALLBACK_RE.search(html)
    if match:
        return int(match.group(1))
    return None


async def fetch_followers(client: SteamClient, appid: int) -> FollowerCount | None:
    """None when the game has no community hub, or the page shape changed."""
    url = MEMBERS_URL.format(appid=appid)
    html = await client.get_text(url)
    count = parse_members_count(html)
    if count is None:
        logger.debug("no_community_group or unparsable members page for %s", appid)
        return None
    return FollowerCount(appid=appid, followers=count, source_url=url)
