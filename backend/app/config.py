"""Application settings, loaded from the project-root .env."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_ROOT / ".env", Path(".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # The tool layer connects read-only (ADR-6). The read-write URL is kept for
    # the agent_run_log audit trail, which arrives with the agent on Day 5.
    database_url: str = "postgresql://mes:mes@localhost:5432/mes"
    database_url_ro: str = "postgresql://mes_ro:mes_ro@localhost:5432/mes"

    # "This week" is the current ISO week in factory-local time (Day-1 decision).
    factory_timezone: str = "Asia/Tokyo"

    api_port: int = 8000
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"

    db_pool_min_size: int = 1
    db_pool_max_size: int = 8
    db_command_timeout_s: float = 10.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
