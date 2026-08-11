from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Steam 2026 Indie Intelligence Platform"
    app_env: str = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://steam:steam@localhost:5432/steam2026"

    exports_dir: str = "/data/exports"
    logs_dir: str = "/data/logs"
    media_dir: str = "/data/media"

    # Community videos — lazy per-game fetching. Empty key = platform skipped.
    youtube_api_key: str = ""
    twitch_client_id: str = ""
    twitch_client_secret: str = ""
    # Daily unit budgets (safety net, not the real provider limit): YouTube's
    # free tier is 10k units/day — leave headroom for other tooling.
    youtube_daily_quota: int = 8000
    twitch_daily_quota: int = 50000
    video_cache_ttl_hours: int = 24
    # Submission-form protection + admin review access.
    submission_cooldown_minutes: int = 10
    admin_token: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
