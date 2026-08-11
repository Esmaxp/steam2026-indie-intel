"""Lazy per-game community videos: fetch on first page view, cache in Postgres.

Scale strategy for ~14k games:
- Nothing is pre-fetched. A game's videos are fetched only when its page is
  opened AND it has approved channel info in `game_channels`.
- Results live in the `video_cache` table (TTL below); a cache hit costs zero
  API units.
- Every third-party call is counted in `api_usage_daily` first. When the daily
  budget is spent, the fetcher degrades gracefully: stale cache if present,
  otherwise a "quota_exhausted" payload — never an error page.
"""

import asyncio
import datetime
import logging
import re

import aiohttp
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import ApiUsageDaily, GameChannels, VideoCache

logger = logging.getLogger(__name__)

MAX_CLIPS_PER_PLATFORM = 12

# One lock per appid so concurrent views of the same page trigger one fetch,
# not N. Bounded by the catalog size (~14k) — fine to keep in memory.
_fetch_locks: dict[int, asyncio.Lock] = {}

_YT_CHANNEL_ID_RE = re.compile(r"youtube\.com/channel/(UC[0-9A-Za-z_-]{10,})", re.I)
_YT_HANDLE_RE = re.compile(r"youtube\.com/@([0-9A-Za-z_.-]{3,30})", re.I)
_YT_BARE_HANDLE_RE = re.compile(r"^@([0-9A-Za-z_.-]{3,30})$")
# Legacy URL forms — common on older official game sites (auto-detected links).
_YT_USER_RE = re.compile(r"youtube\.com/user/([0-9A-Za-z_.-]{3,30})", re.I)
_YT_VANITY_RE = re.compile(r"youtube\.com/c/([0-9A-Za-z_.-]{3,30})", re.I)


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


async def consume_quota(db: AsyncSession, platform: str, units: int) -> bool:
    """Reserve `units` from today's budget. Commits immediately so the counter
    survives even if the subsequent fetch fails. Returns False when spent."""
    settings = get_settings()
    limit = (
        settings.youtube_daily_quota if platform == "youtube"
        else settings.twitch_daily_quota
    )
    stmt = (
        pg_insert(ApiUsageDaily)
        .values(day=datetime.date.today(), platform=platform, units=units)
        .on_conflict_do_update(
            index_elements=["day", "platform"],
            set_={"units": ApiUsageDaily.units + units},
        )
        .returning(ApiUsageDaily.units)
    )
    used = (await db.execute(stmt)).scalar_one()
    await db.commit()
    if used > limit:
        logger.warning("Daily %s quota spent (%d/%d units)", platform, used, limit)
        return False
    return True


async def _resolve_youtube_channel_id(
    http: aiohttp.ClientSession, key: str, url: str
) -> str | None:
    """Channel URL/handle → UC… id. Direct /channel/ URLs cost 0 units."""
    match = _YT_CHANNEL_ID_RE.search(url)
    if match:
        return match.group(1)
    user_match = _YT_USER_RE.search(url)
    handle_match = (
        _YT_HANDLE_RE.search(url)
        or _YT_BARE_HANDLE_RE.match(url.strip())
        or _YT_VANITY_RE.search(url)  # /c/ vanity names usually match the handle
    )
    if user_match:
        params = {"part": "id", "forUsername": user_match.group(1), "key": key}
    elif handle_match:
        params = {"part": "id", "forHandle": f"@{handle_match.group(1)}", "key": key}
    else:
        return None
    async with http.get(
        "https://www.googleapis.com/youtube/v3/channels", params=params
    ) as res:
        if res.status != 200:
            return None
        data = await res.json()
    return (data.get("items") or [{}])[0].get("id")


async def _fetch_youtube_view_counts(
    http: aiohttp.ClientSession, key: str, video_ids: list[str]
) -> dict[str, int]:
    """videos.list statistics for up to 50 ids in one call (1 quota unit).
    Best-effort: returns {} on any error — view counts are never worth failing
    the whole fetch over."""
    if not video_ids:
        return {}
    try:
        async with http.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "statistics", "id": ",".join(video_ids), "key": key},
        ) as res:
            if res.status != 200:
                return {}
            data = await res.json()
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return {}
    counts = {}
    for item in data.get("items", []):
        raw = (item.get("statistics") or {}).get("viewCount")
        if item.get("id") and raw is not None:
            try:
                counts[item["id"]] = int(raw)
            except (TypeError, ValueError):
                continue
    return counts


async def _fetch_youtube(
    http: aiohttp.ClientSession, key: str, channel_id: str
) -> list[dict] | dict:
    # Uploads playlist id is derivable from the channel id (UC… → UU…),
    # saving the channels.list call on every fetch.
    uploads = "UU" + channel_id[2:]
    async with http.get(
        "https://www.googleapis.com/youtube/v3/playlistItems",
        params={
            "part": "snippet",
            "playlistId": uploads,
            "maxResults": MAX_CLIPS_PER_PLATFORM,
            "key": key,
        },
    ) as res:
        if res.status != 200:
            return {"error": f"playlistItems HTTP {res.status}"}
        data = await res.json()
    items = [
        item
        for item in data.get("items", [])
        if item.get("snippet", {}).get("resourceId", {}).get("videoId")
    ]
    video_ids = [item["snippet"]["resourceId"]["videoId"] for item in items]
    view_counts = await _fetch_youtube_view_counts(http, key, video_ids)
    return [
        {
            "platform": "youtube",
            "title": item["snippet"].get("title", ""),
            "url": "https://www.youtube.com/watch?v="
            + item["snippet"]["resourceId"]["videoId"],
            "thumbnail": (item["snippet"].get("thumbnails") or {})
            .get("medium", {})
            .get("url"),
            "published_at": item["snippet"].get("publishedAt"),
            "views": view_counts.get(item["snippet"]["resourceId"]["videoId"]),
            "source": "api",
        }
        for item in items
    ]


_twitch_token: dict | None = None


async def _twitch_app_token(http: aiohttp.ClientSession) -> str | None:
    global _twitch_token
    settings = get_settings()
    if _twitch_token and _twitch_token["expires_at"] > _now():
        return _twitch_token["token"]
    async with http.post(
        "https://id.twitch.tv/oauth2/token",
        params={
            "client_id": settings.twitch_client_id,
            "client_secret": settings.twitch_client_secret,
            "grant_type": "client_credentials",
        },
    ) as res:
        if res.status != 200:
            return None
        data = await res.json()
    _twitch_token = {
        "token": data["access_token"],
        "expires_at": _now() + datetime.timedelta(seconds=data["expires_in"] - 60),
    }
    return _twitch_token["token"]


async def _fetch_twitch(http: aiohttp.ClientSession, login: str) -> list[dict] | dict:
    settings = get_settings()
    token = await _twitch_app_token(http)
    if token is None:
        return {"error": "token request failed"}
    headers = {"Client-ID": settings.twitch_client_id, "Authorization": f"Bearer {token}"}
    async with http.get(
        "https://api.twitch.tv/helix/users", params={"login": login}, headers=headers
    ) as res:
        if res.status != 200:
            return {"error": f"users HTTP {res.status}"}
        user_data = await res.json()
    user_id = (user_data.get("data") or [{}])[0].get("id")
    if not user_id:
        return {"error": f"user '{login}' not found"}
    async with http.get(
        "https://api.twitch.tv/helix/clips",
        params={"broadcaster_id": user_id, "first": MAX_CLIPS_PER_PLATFORM},
        headers=headers,
    ) as res:
        if res.status != 200:
            return {"error": f"clips HTTP {res.status}"}
        clips_data = await res.json()
    return [
        {
            "platform": "twitch",
            "title": clip.get("title", ""),
            "url": clip["url"],
            "thumbnail": clip.get("thumbnail_url"),
            "published_at": clip.get("created_at"),
            "views": clip.get("view_count"),
            "source": "api",
        }
        for clip in clips_data.get("data", [])
        if clip.get("url")
    ]


def _manual_clips(channels: GameChannels) -> list[dict]:
    clips = []
    for link in channels.manual_links or []:
        if not isinstance(link, dict) or not link.get("url"):
            continue
        platform = link.get("platform", "link")
        clips.append(
            {
                "platform": platform,
                "title": link.get("title") or f"{platform.capitalize()} profile",
                "url": link["url"],
                "thumbnail": link.get("thumbnail"),
                "published_at": link.get("published_at"),
                "views": None,  # manual links carry no view-count data
                "source": "manual",
            }
        )
    return clips


def _channels_summary(channels: GameChannels | None) -> dict | None:
    if channels is None:
        return None
    return {
        "youtube_url": channels.youtube_url,
        "twitch_login": channels.twitch_login,
        "manual_links": channels.manual_links or [],
    }


def _has_channel_info(channels: GameChannels | None) -> bool:
    return channels is not None and bool(
        channels.youtube_url or channels.twitch_login or channels.manual_links
    )


async def get_game_videos(db: AsyncSession, appid: int) -> dict:
    """Cache-first video lookup; see module docstring for the strategy."""
    settings = get_settings()
    channels = await db.get(GameChannels, appid)
    if not _has_channel_info(channels):
        return {
            "status": "no_channels",
            "clips": [],
            "unavailable": [],
            "fetched_at": None,
            "channels": None,
        }

    lock = _fetch_locks.setdefault(appid, asyncio.Lock())
    async with lock:
        cache_row = await db.get(VideoCache, appid)
        ttl = datetime.timedelta(hours=settings.video_cache_ttl_hours)
        if cache_row is not None and _now() - cache_row.fetched_at < ttl:
            return {"status": "ok", "channels": _channels_summary(channels), **cache_row.payload}

        clips: list[dict] = _manual_clips(channels)
        unavailable: list[dict] = []
        quota_blocked = False

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20)
        ) as http:
            if channels.youtube_url:
                if not settings.youtube_api_key:
                    unavailable.append({"platform": "youtube", "reason": "not configured"})
                # 3 units: playlistItems (1) + videos.list statistics (1),
                # plus headroom for the occasional channel-id resolution (1).
                elif not await consume_quota(db, "youtube", 3):
                    quota_blocked = True
                else:
                    try:
                        channel_id = channels.youtube_channel_id
                        if not channel_id:
                            channel_id = await _resolve_youtube_channel_id(
                                http, settings.youtube_api_key, channels.youtube_url
                            )
                            if channel_id:
                                channels.youtube_channel_id = channel_id
                                await db.commit()
                        if channel_id:
                            result = await _fetch_youtube(
                                http, settings.youtube_api_key, channel_id
                            )
                            if isinstance(result, list):
                                clips.extend(result)
                            else:
                                unavailable.append({"platform": "youtube", **result})
                        else:
                            unavailable.append(
                                {"platform": "youtube", "error": "channel not resolvable"}
                            )
                    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                        unavailable.append({"platform": "youtube", "error": str(exc)})

            if channels.twitch_login:
                if not (settings.twitch_client_id and settings.twitch_client_secret):
                    unavailable.append({"platform": "twitch", "reason": "not configured"})
                elif not await consume_quota(db, "twitch", 2):
                    quota_blocked = True
                else:
                    try:
                        result = await _fetch_twitch(http, channels.twitch_login)
                        if isinstance(result, list):
                            clips.extend(result)
                        else:
                            unavailable.append({"platform": "twitch", **result})
                    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                        unavailable.append({"platform": "twitch", "error": str(exc)})

        # Graceful degradation: prefer a stale cache over a partial/blocked fetch.
        api_errors = [u for u in unavailable if "error" in u]
        if (quota_blocked or api_errors) and cache_row is not None:
            return {
                "status": "stale",
                "channels": _channels_summary(channels),
                **cache_row.payload,
            }
        if quota_blocked and not clips:
            return {
                "status": "quota_exhausted",
                "clips": [],
                "unavailable": unavailable,
                "fetched_at": None,
                "channels": _channels_summary(channels),
            }

        clips.sort(key=lambda c: c.get("published_at") or "", reverse=True)
        payload = {
            "clips": clips,
            "unavailable": unavailable,
            "fetched_at": _now().isoformat(),
        }
        upsert = (
            pg_insert(VideoCache)
            .values(appid=appid, payload=payload, fetched_at=_now())
            .on_conflict_do_update(
                index_elements=["appid"],
                set_={"payload": payload, "fetched_at": _now()},
            )
        )
        await db.execute(upsert)
        await db.commit()
        return {"status": "ok", "channels": _channels_summary(channels), **payload}


async def invalidate_cache(db: AsyncSession, appid: int) -> None:
    await db.execute(sa.delete(VideoCache).where(VideoCache.appid == appid))
