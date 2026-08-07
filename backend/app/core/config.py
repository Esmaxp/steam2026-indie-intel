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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
