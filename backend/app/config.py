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

    # --- LLM (ADR-5: provider-abstracted, local-first) --------------------
    # openai_compatible | anthropic | none.
    #
    # The factory's production environment is isolated, so the prototype runs a
    # locally deployed open-weight model by default: questions and MES data stay
    # inside the application environment. `anthropic` remains available as a
    # development reference. With no provider reachable the agent falls back to
    # deterministic rule-based understanding and says so in every response.
    llm_provider: str = "openai_compatible"
    llm_model: str = "qwen2.5:14b-instruct"
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = ""
    # Generous: loading a 7B+ model into memory on first use can take a minute
    # or more on CPU, and that load happens inside the first request.
    llm_timeout_s: float = 180.0
    # Force that load at startup instead, so the factory manager's first
    # question is not the one that pays for it. It runs in the background with
    # its own, much longer budget: warming is slow but must not block startup,
    # and it must not be cut off by the per-request timeout.
    llm_warmup: bool = True
    llm_warmup_timeout_s: float = 900.0
    # Only the local provider uses this: a small model is markedly more
    # consistent at 0, and local runtimes accept the parameter. Current hosted
    # Claude models reject it outright, so it is never sent to them.
    llm_temperature: float = 0.0
    # Leave empty to negotiate (json_schema -> json_object -> prompt), or pin a
    # mode once you know what your endpoint supports.
    llm_structured_mode: str = ""
    anthropic_api_key: str = ""

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
