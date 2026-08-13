from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Steam 2026 Indie Intelligence Platform"
    app_env: str = "development"
    log_level: str = "INFO"

    # Local (non-Docker) fallback: 9432 is the host port the db container publishes.
    database_url: str = "postgresql+asyncpg://steam:steam@localhost:9432/steam2026"

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
    # Submission-form protection. Admin routes are unauthenticated for now
    # — see app.api.v1.videos.require_admin.
    submission_cooldown_minutes: int = 10

    # Optional AI-based 2D/3D classification (workers/classify_dimension_vision
    # reads a screenshot; workers/classify_dimension_similarity reasons from
    # metadata). Empty key = both workers refuse to run; nothing else uses this.
    anthropic_api_key: str = ""
    anthropic_vision_model: str = "claude-opus-5"
    anthropic_text_model: str = "claude-opus-5"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
