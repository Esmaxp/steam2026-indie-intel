import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ClipOut(BaseModel):
    platform: str
    title: str
    url: str
    thumbnail: str | None = None
    published_at: str | None = None
    views: int | None = None
    source: str = "api"


class ChannelsOut(BaseModel):
    youtube_url: str | None = None
    twitch_login: str | None = None
    manual_links: list[dict] = []


class GameVideosOut(BaseModel):
    """status: ok | stale (expired cache served because fetch was blocked) |
    no_channels | quota_exhausted."""

    status: str
    clips: list[ClipOut] = []
    unavailable: list[dict] = []
    fetched_at: str | None = None
    channels: ChannelsOut | None = None


class ChannelSubmissionIn(BaseModel):
    youtube_url: str = Field("", max_length=300)
    twitch_login: str = Field("", max_length=300)
    links: list[str] = Field(default_factory=list, max_length=5)
    # Honeypot — hidden in the UI; bots that fill it are silently dropped.
    nickname: str = Field("", max_length=100)


class SubmissionOut(BaseModel):
    id: int
    appid: int
    game_name: str | None = None
    youtube_url: str | None = None
    twitch_login: str | None = None
    other_links: list[dict] = []
    source: str = "developer_submitted"
    found_on: str | None = None
    status: str
    created_at: datetime.datetime
    reviewed_at: datetime.datetime | None = None
    review_note: str | None = None


class ReviewIn(BaseModel):
    note: str = Field("", max_length=500)


class BulkReviewIn(BaseModel):
    """Explicit id list only — which rows get reviewed is always the admin's
    choice; there is deliberately no server-side auto-approval rule."""

    ids: list[int] = Field(min_length=1, max_length=200)
    action: Literal["approve", "reject"]
    note: str = Field("", max_length=500)
