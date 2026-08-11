"""Scan stored official game websites for social channel links.

Reads the `games.website` values backfilled earlier (never refetches Steam),
fetches each site's HTML once, pattern-matches YouTube / Twitch / TikTok /
Instagram / X profile links and files them as PENDING channel submissions
with source="auto_detected" — nothing goes live without manual review in the
existing admin queue.

Safety / politeness:
- robots.txt is honored (cached per host); disallowed sites are skipped.
- One request per site, short timeout, no retries.
- Throttled to --per-minute sites; run in batches with --limit.
- Resumable: every checked site gets a `website_scans` row; sites scanned
  within --rescan-days are skipped, so stop/restart continues where it left.
- Games with approved channel info or an already-pending submission are
  never touched (no duplicate proposals).

Usage:
    python -m workers.scan_websites [--limit 200] [--per-minute 30] [--rescan-days 7]
    docker compose run --rm scanner
"""

import argparse
import asyncio
import datetime
import re
import urllib.robotparser
from urllib.parse import urlparse

import aiohttp
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import async_session_factory
from app.models import ChannelSubmission, Game, GameChannels, WebsiteScan
from scraper.common.logging import setup_logging

USER_AGENT = "Steam2026IndieIntelligence/0.1 (+channel discovery; respects robots.txt)"
FETCH_TIMEOUT = aiohttp.ClientTimeout(total=8)
MAX_HTML_BYTES = 2_000_000
PROGRESS_EVERY = 25

# Profile-shaped links only — watch?v= embeds and bare domains don't match.
_PATTERNS = {
    "youtube": re.compile(
        r"youtube\.com/(@[0-9A-Za-z_.-]{3,30}|channel/UC[0-9A-Za-z_-]{10,}"
        r"|c/[0-9A-Za-z_.-]{3,30}|user/[0-9A-Za-z_.-]{3,30})",
        re.I,
    ),
    "twitch": re.compile(r"twitch\.tv/([A-Za-z0-9_]{3,25})(?![\w])", re.I),
    "tiktok": re.compile(r"tiktok\.com/(@[0-9A-Za-z_.-]{2,30})", re.I),
    "instagram": re.compile(r"instagram\.com/([0-9A-Za-z_.]{2,30})(?![\w.])", re.I),
    "x": re.compile(r"(?:twitter|x)\.com/([0-9A-Za-z_]{2,15})(?![\w])", re.I),
}

# First path segments that are site features, not user profiles.
_NOT_PROFILES = {
    "twitch": {"videos", "directory", "downloads", "p", "search", "settings",
               "jobs", "turbo", "login", "signup", "friends", "subscriptions"},
    "instagram": {"p", "reel", "reels", "explore", "accounts", "share",
                  "stories", "about", "developer", "legal"},
    "x": {"intent", "share", "hashtag", "home", "search", "i", "login",
          "signup", "privacy", "tos", "settings", "explore"},
}


def extract_candidates(html: str) -> dict[str, list[str]]:
    """Platform → deduped clean profile URLs found in the page."""
    found: dict[str, list[str]] = {}
    for platform, pattern in _PATTERNS.items():
        seen = set()
        urls = []
        for match in pattern.finditer(html):
            ident = match.group(1)
            key = ident.lower()
            if key in seen or key.split("/")[0] in _NOT_PROFILES.get(platform, set()):
                continue
            seen.add(key)
            if platform == "youtube":
                urls.append(f"https://www.youtube.com/{ident}")
            elif platform == "twitch":
                urls.append(ident.lower())  # login, not URL
            elif platform == "tiktok":
                urls.append(f"https://www.tiktok.com/{ident}")
            elif platform == "instagram":
                urls.append(f"https://www.instagram.com/{ident}")
            else:
                urls.append(f"https://x.com/{ident}")
        if urls:
            found[platform] = urls
    return found


class RobotsCache:
    """Per-host robots.txt verdicts; fetch errors count as allowed."""

    def __init__(self, http: aiohttp.ClientSession):
        self.http = http
        self._parsers: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    async def allowed(self, url: str) -> bool:
        host = urlparse(url).netloc
        if host not in self._parsers:
            parser = urllib.robotparser.RobotFileParser()
            try:
                async with self.http.get(
                    f"{urlparse(url).scheme}://{host}/robots.txt"
                ) as res:
                    if res.status == 200:
                        body = (await res.content.read(200_000)).decode("utf-8", "ignore")
                        parser.parse(body.splitlines())
                    else:
                        parser = None  # no robots.txt → allowed
            except (aiohttp.ClientError, asyncio.TimeoutError):
                parser = None
            self._parsers[host] = parser
        parser = self._parsers[host]
        return parser is None or parser.can_fetch(USER_AGENT, url)


async def fetch_html(http: aiohttp.ClientSession, url: str) -> tuple[str | None, str]:
    """Returns (html, outcome). One attempt, short timeout, no retries."""
    try:
        async with http.get(url, allow_redirects=True) as res:
            if res.status != 200:
                return None, "fetch_error"
            content_type = res.headers.get("Content-Type", "")
            if "html" not in content_type.lower():
                return None, "not_html"
            raw = await res.content.read(MAX_HTML_BYTES)
            return raw.decode("utf-8", "ignore"), "ok"
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return None, "fetch_error"


async def select_scannable(rescan_days: int, limit: int) -> list[tuple[int, str]]:
    """Games with a website but no channels, no pending submission, and no
    recent scan record."""
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=rescan_days
    )
    async with async_session_factory() as db:
        stmt = (
            sa.select(Game.appid, Game.website)
            .where(
                Game.website.is_not(None),
                Game.website != "",
                ~sa.exists().where(GameChannels.appid == Game.appid),
                ~sa.exists().where(
                    ChannelSubmission.appid == Game.appid,
                    ChannelSubmission.status == "pending",
                ),
                ~sa.exists().where(
                    WebsiteScan.appid == Game.appid, WebsiteScan.scanned_at > cutoff
                ),
            )
            .order_by(Game.appid)
            .limit(limit)
        )
        return [(appid, website) for appid, website in (await db.execute(stmt)).all()]


async def record_scan(appid: int, outcome: str, links_found: int) -> None:
    async with async_session_factory() as db:
        stmt = (
            pg_insert(WebsiteScan)
            .values(
                appid=appid,
                outcome=outcome,
                links_found=links_found,
                scanned_at=sa.func.now(),
            )
            .on_conflict_do_update(
                index_elements=["appid"],
                set_={
                    "outcome": outcome,
                    "links_found": links_found,
                    "scanned_at": sa.func.now(),
                },
            )
        )
        await db.execute(stmt)
        await db.commit()


async def file_submission(appid: int, website: str, candidates: dict) -> int:
    """Create one pending auto_detected submission; returns links filed."""
    youtube = (candidates.get("youtube") or [None])[0]
    twitch = (candidates.get("twitch") or [None])[0]
    other = [
        {"platform": platform, "url": url}
        for platform in ("tiktok", "instagram", "x")
        for url in candidates.get(platform, [])[:2]
    ]
    count = int(bool(youtube)) + int(bool(twitch)) + len(other)
    if count == 0:
        return 0
    async with async_session_factory() as db:
        db.add(
            ChannelSubmission(
                appid=appid,
                youtube_url=youtube,
                twitch_login=twitch,
                other_links=other or None,
                source="auto_detected",
                found_on=website,
            )
        )
        await db.commit()
    return count


async def run(limit: int, per_minute: int, rescan_days: int) -> None:
    logger = setup_logging("scan_websites")
    games = await select_scannable(rescan_days, limit)
    if not games:
        logger.info("Nothing to scan — all eligible websites checked recently.")
        return
    logger.info(
        "Scanning %d game websites (max %d/minute, rescan window %dd)",
        len(games), per_minute, rescan_days,
    )

    interval = 60.0 / max(1, per_minute)
    scanned = 0
    total_links = 0
    with_candidates = 0

    async with aiohttp.ClientSession(
        headers={"User-Agent": USER_AGENT}, timeout=FETCH_TIMEOUT
    ) as http:
        robots = RobotsCache(http)
        for appid, website in games:
            started = asyncio.get_event_loop().time()

            if not website.lower().startswith(("http://", "https://")):
                website = f"https://{website}"
            try:
                allowed = await robots.allowed(website)
            except Exception:
                allowed = True
            if not allowed:
                await record_scan(appid, "robots_disallowed", 0)
            else:
                html, outcome = await fetch_html(http, website)
                if html is None:
                    await record_scan(appid, outcome, 0)
                else:
                    candidates = extract_candidates(html)
                    filed = await file_submission(appid, website, candidates)
                    total_links += filed
                    if filed:
                        with_candidates += 1
                    await record_scan(appid, "found" if filed else "none", filed)

            scanned += 1
            if scanned % PROGRESS_EVERY == 0 or scanned == len(games):
                logger.info(
                    "Scanned %d / %d games — %d candidate links across %d games",
                    scanned, len(games), total_links, with_candidates,
                )

            elapsed = asyncio.get_event_loop().time() - started
            if elapsed < interval and scanned < len(games):
                await asyncio.sleep(interval - elapsed)

    logger.info(
        "Done: %d sites scanned, %d pending submissions filed (%d links). "
        "Review them at /admin/submissions.",
        scanned, with_candidates, total_links,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect social channel links on stored game websites"
    )
    parser.add_argument(
        "--limit", type=int, default=200, help="max sites this run (batching)"
    )
    parser.add_argument(
        "--per-minute", type=int, default=30, help="max sites fetched per minute"
    )
    parser.add_argument(
        "--rescan-days", type=int, default=7,
        help="skip sites scanned within this many days",
    )
    args = parser.parse_args()
    asyncio.run(run(args.limit, args.per_minute, args.rescan_days))


if __name__ == "__main__":
    main()
