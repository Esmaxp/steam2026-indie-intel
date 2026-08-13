"""Per-game community videos + developer channel submissions.

- GET  /games/{appid}/videos              lazy fetch + cache (see services.videos)
- POST /games/{appid}/channel-submissions self-service form → pending review
- /admin/channel-submissions              review queue (see require_admin:
                                          auth is a no-op for now)
"""

import datetime
import re
from urllib.parse import urlparse

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.models import ChannelSubmission, Game, GameChannels
from app.schemas.videos import (
    BulkReviewIn,
    ChannelSubmissionIn,
    GameVideosOut,
    ReviewIn,
    SubmissionOut,
)
from app.services.videos import get_game_videos, invalidate_cache

router = APIRouter()
admin_router = APIRouter()

_TWITCH_LOGIN_RE = re.compile(r"^[A-Za-z0-9_]{3,25}$")
_YT_URL_RE = re.compile(
    r"^https?://(www\.)?youtube\.com/(channel/UC[0-9A-Za-z_-]{10,}|@[0-9A-Za-z_.-]{3,30})/?$",
    re.I,
)
_BARE_HANDLE_RE = re.compile(r"^@[0-9A-Za-z_.-]{3,30}$")

_LINK_PLATFORMS = {
    "tiktok.com": "tiktok",
    "instagram.com": "instagram",
    "x.com": "x",
    "twitter.com": "x",
}


def _normalize_youtube(raw: str) -> str | None:
    """Accepts a channel URL or @handle; returns a canonical URL or None."""
    value = raw.strip()
    if not value:
        return None
    if _BARE_HANDLE_RE.match(value):
        return f"https://www.youtube.com/{value}"
    if _YT_URL_RE.match(value):
        return value.rstrip("/")
    raise HTTPException(
        status_code=422,
        detail="YouTube must be a channel URL (youtube.com/channel/UC… or youtube.com/@handle) or a bare @handle",
    )


def _normalize_twitch(raw: str) -> str | None:
    """Accepts a twitch.tv URL or bare login; returns the login or None."""
    value = raw.strip()
    if not value:
        return None
    if "twitch.tv/" in value.lower():
        value = urlparse(value if "//" in value else f"https://{value}").path.strip("/").split("/")[0]
    if _TWITCH_LOGIN_RE.match(value):
        return value.lower()
    raise HTTPException(status_code=422, detail="Twitch must be a twitch.tv URL or a valid login")


def _normalize_links(raw_links: list[str]) -> list[dict]:
    links = []
    for raw in raw_links:
        value = raw.strip()
        if not value:
            continue
        if len(value) > 300:
            raise HTTPException(status_code=422, detail="Link too long")
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise HTTPException(status_code=422, detail=f"Not a valid URL: {value}")
        host = parsed.hostname.lower().removeprefix("www.")
        platform = _LINK_PLATFORMS.get(host)
        if platform is None:
            raise HTTPException(
                status_code=422,
                detail="Only TikTok, Instagram and X profile URLs are accepted here",
            )
        links.append({"platform": platform, "url": value})
    return links


async def _require_game(db: AsyncSession, appid: int) -> None:
    exists = (
        await db.execute(sa.select(Game.appid).where(Game.appid == appid))
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail="Game not found")


@router.get("/{appid}/videos", response_model=GameVideosOut)
async def game_videos(appid: int, db: AsyncSession = Depends(get_db)) -> GameVideosOut:
    await _require_game(db, appid)
    return GameVideosOut(**await get_game_videos(db, appid))


@router.post("/{appid}/channel-submissions", status_code=202)
async def submit_channels(
    appid: int,
    body: ChannelSubmissionIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _require_game(db, appid)

    # Honeypot: bots fill every field. Pretend success, store nothing.
    if body.nickname.strip():
        return {"status": "received"}

    youtube = _normalize_youtube(body.youtube_url)
    twitch = _normalize_twitch(body.twitch_login)
    links = _normalize_links(body.links)
    if not (youtube or twitch or links):
        raise HTTPException(status_code=422, detail="Submit at least one channel or profile")

    settings = get_settings()
    ip = request.client.host if request.client else None
    if ip:
        cooldown = datetime.timedelta(minutes=settings.submission_cooldown_minutes)
        recent = (
            await db.execute(
                sa.select(ChannelSubmission.id)
                .where(
                    ChannelSubmission.submitter_ip == ip,
                    ChannelSubmission.created_at
                    > datetime.datetime.now(datetime.timezone.utc) - cooldown,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if recent is not None:
            raise HTTPException(
                status_code=429,
                detail=f"Please wait {settings.submission_cooldown_minutes} minutes between submissions",
            )

    db.add(
        ChannelSubmission(
            appid=appid,
            youtube_url=youtube,
            twitch_login=twitch,
            other_links=links or None,
            submitter_ip=ip,
            source="developer_submitted",
        )
    )
    await db.commit()
    return {"status": "received"}


# ---------------------------------------------------------------- admin ----


def require_admin() -> None:
    """Authorisation seam for every /admin route — CURRENTLY A NO-OP.

    The shared-token check was removed pending real authentication. Until that
    lands, ANY caller that can reach this API has full admin access: approving
    channel submissions, and starting collector sweeps that run for hours and
    write CONFIRMED rows.

    That is acceptable only while the backend is bound to localhost. Do not
    expose port 9100 beyond the host until this function actually
    authenticates.

    It stays wired into every admin route on purpose: implementing auth means
    changing this one function, not hunting down decorators.
    """
    return None


def _submission_out(sub: ChannelSubmission, game_name: str | None) -> SubmissionOut:
    return SubmissionOut(
        id=sub.id,
        appid=sub.appid,
        game_name=game_name,
        youtube_url=sub.youtube_url,
        twitch_login=sub.twitch_login,
        other_links=sub.other_links or [],
        source=sub.source,
        found_on=sub.found_on,
        status=sub.status,
        created_at=sub.created_at,
        reviewed_at=sub.reviewed_at,
        review_note=sub.review_note,
    )


@admin_router.get(
    "/channel-submissions",
    response_model=list[SubmissionOut],
    dependencies=[Depends(require_admin)],
)
async def list_submissions(
    status: str = "pending", db: AsyncSession = Depends(get_db)
) -> list[SubmissionOut]:
    rows = (
        await db.execute(
            sa.select(ChannelSubmission, Game.name)
            .join(Game, Game.appid == ChannelSubmission.appid)
            .where(ChannelSubmission.status == status)
            .order_by(ChannelSubmission.created_at.asc())
            .limit(200)
        )
    ).all()
    return [_submission_out(sub, name) for sub, name in rows]


async def _load_pending(db: AsyncSession, submission_id: int) -> ChannelSubmission:
    sub = await db.get(ChannelSubmission, submission_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    if sub.status != "pending":
        raise HTTPException(status_code=409, detail=f"Already {sub.status}")
    return sub


async def _approve_one(db: AsyncSession, sub: ChannelSubmission, note: str) -> None:
    """Write the submission onto the game's channel record (does not commit)."""
    channels = await db.get(GameChannels, sub.appid)
    if channels is None:
        channels = GameChannels(appid=sub.appid, source="submission")
        db.add(channels)
    if sub.youtube_url:
        channels.youtube_url = sub.youtube_url
        channels.youtube_channel_id = None  # re-resolve on next fetch
    if sub.twitch_login:
        channels.twitch_login = sub.twitch_login
    if sub.other_links:
        existing = {link.get("url") for link in channels.manual_links or []}
        merged = list(channels.manual_links or [])
        merged.extend(l for l in sub.other_links if l.get("url") not in existing)
        channels.manual_links = merged
    channels.source = "submission"

    # Next page view fetches fresh data for this game.
    await invalidate_cache(db, sub.appid)

    sub.status = "approved"
    sub.reviewed_at = datetime.datetime.now(datetime.timezone.utc)
    sub.review_note = note or None


def _reject_one(sub: ChannelSubmission, note: str) -> None:
    sub.status = "rejected"
    sub.reviewed_at = datetime.datetime.now(datetime.timezone.utc)
    sub.review_note = note or None


@admin_router.post(
    "/channel-submissions/{submission_id}/approve",
    response_model=SubmissionOut,
    dependencies=[Depends(require_admin)],
)
async def approve_submission(
    submission_id: int, body: ReviewIn | None = None, db: AsyncSession = Depends(get_db)
) -> SubmissionOut:
    sub = await _load_pending(db, submission_id)
    await _approve_one(db, sub, body.note if body else "")
    await db.commit()
    game_name = (
        await db.execute(sa.select(Game.name).where(Game.appid == sub.appid))
    ).scalar_one_or_none()
    return _submission_out(sub, game_name)


@admin_router.post(
    "/channel-submissions/{submission_id}/reject",
    response_model=SubmissionOut,
    dependencies=[Depends(require_admin)],
)
async def reject_submission(
    submission_id: int, body: ReviewIn | None = None, db: AsyncSession = Depends(get_db)
) -> SubmissionOut:
    sub = await _load_pending(db, submission_id)
    _reject_one(sub, body.note if body else "")
    await db.commit()
    game_name = (
        await db.execute(sa.select(Game.name).where(Game.appid == sub.appid))
    ).scalar_one_or_none()
    return _submission_out(sub, game_name)


@admin_router.post(
    "/channel-submissions/bulk-review",
    dependencies=[Depends(require_admin)],
)
async def bulk_review_submissions(
    body: BulkReviewIn, db: AsyncSession = Depends(get_db)
) -> dict:
    """Apply the admin's approve/reject choice to an explicit id list.

    Same per-row behavior as the single endpoints (shared helpers), one
    transaction for the whole batch. Non-pending/unknown ids are skipped.
    No auto-approval logic lives here by design — the id list is the admin's
    hand-picked selection.
    """
    processed: list[int] = []
    skipped: list[int] = []
    for submission_id in body.ids:
        sub = await db.get(ChannelSubmission, submission_id)
        if sub is None or sub.status != "pending":
            skipped.append(submission_id)
            continue
        if body.action == "approve":
            await _approve_one(db, sub, body.note)
        else:
            _reject_one(sub, body.note)
        processed.append(submission_id)
    await db.commit()
    return {"processed": processed, "skipped": skipped}
