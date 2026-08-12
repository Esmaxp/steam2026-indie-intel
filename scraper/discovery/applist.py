"""Steam App List discovery source (exhaustive backstop).

GetAppList/v2 returns every app on Steam (no dates, no genres), so each
candidate must be validated one-by-one through the appdetails API — slow but
complete. Progress is checkpointed in sync_states, so the scan is resumable
and can run incrementally over many sessions.
"""

import logging
from dataclasses import dataclass

from app.models import IndieConfidence
from scraper.classifiers.indie_signals import score_indie_signals
from scraper.common.http import SteamClient
from scraper.discovery.release_date import ParsedRelease, parse_release

logger = logging.getLogger(__name__)

APP_LIST_URL = "https://api.steampowered.com/ISteamApps/GetAppList/v2/"
APP_DETAILS_URL = "https://store.steampowered.com/api/appdetails"
INDIE_GENRE_ID = "23"  # Steam store genre "Indie"


async def fetch_applist(client: SteamClient) -> list[tuple[int, str]]:
    data = await client.get_json(APP_LIST_URL)
    apps = data.get("applist", {}).get("apps", [])
    result = [(a["appid"], a["name"]) for a in apps if a.get("name")]
    logger.info("Steam app list: %d named apps", len(result))
    return result


@dataclass(frozen=True)
class AppCheck:
    appid: int
    keep: bool
    reason: str
    name: str | None = None
    release: ParsedRelease | None = None
    coming_soon: bool = False
    # How the app qualified — auditable downstream, same idea as
    # channel_submissions.source: indie_tag (Steam Indie genre present) |
    # self_published_no_tag | boutique_label_no_tag (tag-less fallback).
    discovery_method: str = "indie_tag"


def evaluate_app(
    appid: int, details: dict, target_year: int, include_untagged: bool = False
) -> AppCheck:
    """Pure keep/drop decision over an appdetails payload (testable offline)."""
    if details.get("type") != "game":
        return AppCheck(appid, keep=False, reason=f"type_{details.get('type', 'unknown')}")

    genres = details.get("genres") or []
    is_indie = any(
        str(g.get("id")) == INDIE_GENRE_ID or str(g.get("description", "")).lower() == "indie"
        for g in genres
    )
    discovery_method = "indie_tag"
    if not is_indie:
        if not include_untagged:
            return AppCheck(appid, keep=False, reason="not_indie")
        # Opt-in fallback: only the two publisher signals reliable enough to
        # stand in for the missing tag. The generic "third-party publisher,
        # not on any known-large list" MEDIUM branch stays tag-gated — it
        # would admit droves of non-indie small/mid studios.
        signal = score_indie_signals(
            details.get("developers") or [], details.get("publishers") or []
        )
        if signal.is_indie and signal.confidence == IndieConfidence.HIGH:
            discovery_method = "self_published_no_tag"
        elif (
            signal.is_indie
            and signal.confidence == IndieConfidence.MEDIUM
            and signal.reason.startswith("boutique")
        ):
            discovery_method = "boutique_label_no_tag"
        else:
            return AppCheck(appid, keep=False, reason="not_indie_no_tag")

    release_info = details.get("release_date") or {}
    parsed = parse_release(release_info.get("date"))
    if parsed.year != target_year:
        return AppCheck(appid, keep=False, reason=f"year_{parsed.year or 'unknown'}")

    return AppCheck(
        appid,
        keep=True,
        reason="ok",
        name=details.get("name"),
        release=parsed,
        coming_soon=bool(release_info.get("coming_soon")),
        discovery_method=discovery_method,
    )


async def check_app(
    client: SteamClient, appid: int, target_year: int, include_untagged: bool = False
) -> AppCheck:
    """Fetch appdetails and decide whether this is a <target_year> indie game."""
    data = await client.get_json(
        APP_DETAILS_URL, params={"appids": appid, "cc": "us", "l": "english"}
    )
    entry = data.get(str(appid)) or {}
    if not entry.get("success") or not entry.get("data"):
        return AppCheck(appid, keep=False, reason="no_store_data")

    return evaluate_app(appid, entry["data"], target_year, include_untagged)
