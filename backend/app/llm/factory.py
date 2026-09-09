"""Select the configured provider, or none at all.

Local-first: the default is an open-weight model served inside the application
environment, matching the factory's isolated production target. Claude stays
available as a development reference.

Returning `None` is a supported outcome, not an error. With no model configured
the agent falls back to its deterministic rule-based understanding (see
`app/agent/extractor.py`), which keeps the demo, the tests and an air-gapped
site running when the model endpoint is unavailable. Every response records
which path produced it, so a degraded run is never mistaken for a full one.
"""

from __future__ import annotations

import logging
import os

from app.config import Settings
from app.llm.base import LLMClient

log = logging.getLogger(__name__)


def build_llm_client(settings: Settings) -> tuple[LLMClient | None, str]:
    """Return (client, reason). `reason` explains a None as well as a client."""
    provider = (settings.llm_provider or "").strip().lower()

    if provider in ("", "none", "disabled"):
        return None, "No LLM provider is configured; using deterministic understanding."

    if provider == "anthropic":
        has_credentials = bool(
            settings.anthropic_api_key
            or os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        )
        if not has_credentials:
            return None, (
                "LLM_PROVIDER=anthropic but no credentials were found "
                "(ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN); using deterministic understanding."
            )
        try:
            from app.llm.anthropic_client import AnthropicLLMClient
        except ImportError:
            return None, (
                "LLM_PROVIDER=anthropic but the anthropic SDK is not installed "
                "(pip install 'mes-copilot-backend[anthropic]'); using deterministic understanding."
            )

        client = AnthropicLLMClient(
            model=settings.llm_model,
            api_key=settings.anthropic_api_key or None,
            timeout_s=settings.llm_timeout_s,
        )
        return client, f"Anthropic provider ready ({settings.llm_model})."

    if provider in ("openai_compatible", "local", "vllm", "ollama"):
        if not settings.llm_base_url:
            return None, "LLM_BASE_URL is required for an OpenAI-compatible provider."
        from app.llm.openai_compatible import OpenAICompatibleLLMClient

        client = OpenAICompatibleLLMClient(
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key or None,
            timeout_s=settings.llm_timeout_s,
        )
        return (
            client,
            f"On-premises provider ready ({settings.llm_model} at {settings.llm_base_url}).",
        )

    return None, f"Unknown LLM_PROVIDER '{provider}'; using deterministic understanding."
