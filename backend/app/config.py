"""Application settings, loaded from the project-root .env."""

from datetime import date
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_ROOT / ".env", Path(".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # The tool layer connects read-only (ADR-6). The read-write URL is kept for
    # the agent_run_log audit trail.
    #
    # Both carry credentials, so neither has a default: they come from .env (or
    # the environment) only. A missing value stops startup with a named field
    # instead of quietly connecting with a password written into the code.
    database_url: str
    database_url_ro: str

    @field_validator("database_url", "database_url_ro")
    @classmethod
    def _not_blank(cls, value: str, info) -> str:
        if not value.strip():
            name = info.field_name.upper()
            raise ValueError(f"{name} is empty; set it in .env (see .env.example)")
        return value

    # "This week" is the current ISO week in factory-local time (a scoping decision).
    # It belongs to the factory, not to whoever is asking: the shift calendar,
    # maintenance plan and production history are all dated in the factory's
    # days. Viewers anywhere see times in their own zone (a display concern,
    # handled by the web interface); "today" still means the factory's today.
    factory_timezone: str = "Asia/Tokyo"

    @field_validator("factory_timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        """Refuse to start on a zone the system cannot resolve.

        Without this, `FACTORY_TIMEZONE=China` would pass configuration and fail
        on the first question instead — or worse, on the first question of the
        demo. An IANA name such as `Asia/Shanghai` is required.
        """
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(
                f"FACTORY_TIMEZONE={value!r} is not an IANA time zone; "
                "use a name such as 'Asia/Shanghai' or 'Asia/Tokyo'"
            ) from exc
        return value

    # Pin the factory's calendar to a given day, for rehearsing a demo or
    # testing every day of the week. Pair it with `make db-rehearse DATE=…`
    # so the dataset and the backend agree on what "today" is — seeding for a
    # Tuesday while the backend believes it is Saturday answers questions about
    # a week that does not exist. Empty means the real date, which is the only
    # correct setting outside a rehearsal; /api/health reports when it is set.
    factory_today: date | None = None

    @field_validator("factory_today", mode="before")
    @classmethod
    def _blank_is_real_date(cls, value: object) -> object:
        return None if value in ("", None) else value

    def factory_clock(self):
        from app.timewindow import FactoryClock

        return FactoryClock(self.factory_timezone, _fixed_today=self.factory_today)

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
    # The answer is sampled a little warmer than the extraction, and for a
    # different reason. Reading a question into a typed intent must give the
    # same reading every time, so that runs at 0. Phrasing a settled result at 0
    # writes the *same sentence* for every question whose facts are alike — three
    # questions about CNC-03 came back as one answer, which reads as canned.
    #
    # 0.3 was measured, not guessed: 5 questions × 3 runs at 0 / 0.3 / 0.6 / 0.9
    # gave 10 / 13 / 14 / 15 distinct wordings out of 15, with no rewrites or
    # fallbacks below 0.6. At 0.9 the model began inventing relationships
    # between real figures ("46.3% utilisation, above the 52.0% threshold" — 52
    # is a temperature, and the utilisation limit is 90%), so the ceiling is a
    # truthfulness limit rather than a style one. Raise it only alongside a
    # validator check for whatever it starts inventing.
    llm_explainer_temperature: float = 0.3
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

    @field_validator("llm_temperature", "llm_explainer_temperature")
    @classmethod
    def _sane_temperature(cls, value: float) -> float:
        if not 0.0 <= value <= 2.0:
            raise ValueError("temperature must be between 0 and 2")
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
