"""The provider abstraction (ADR-5).

The Anthropic client is exercised against a stubbed SDK surface: the point is
that the request is built correctly and every failure mode is translated into a
typed error, which is testable without spending money or holding a key.
"""

from __future__ import annotations

import anthropic
import pytest
from pydantic import BaseModel

from app.config import Settings
from app.llm.anthropic_client import AnthropicLLMClient
from app.llm.base import LLMError, LLMRefusalError, LLMUnavailableError, strict_json_schema
from app.llm.factory import build_llm_client


class Reading(BaseModel):
    intent: str
    confidence: float = 0.0


class _Usage:
    input_tokens = 120
    output_tokens = 30


class _Response:
    def __init__(self, parsed=None, stop_reason="end_turn", category=None):
        self.parsed_output = parsed
        self.stop_reason = stop_reason
        self.model = "claude-opus-5"
        self.usage = _Usage()
        self.content = []
        self.stop_details = type("D", (), {"category": category})() if category else None


class _Messages:
    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error
        self.calls: list[dict] = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return self._response


def _client(messages) -> AnthropicLLMClient:
    client = AnthropicLLMClient(model="claude-opus-5", api_key="test")
    client._client.messages = messages
    return client


async def test_structured_extraction_sends_the_schema_and_returns_the_model():
    messages = _Messages(_Response(parsed=Reading(intent="production_capacity", confidence=0.9)))
    result, usage = await _client(messages).structured(
        system="sys", user="How many A12 this week?", output_model=Reading
    )
    assert result.intent == "production_capacity"
    assert usage.input_tokens == 120 and usage.output_tokens == 30
    call = messages.calls[0]
    assert call["model"] == "claude-opus-5"
    assert call["output_format"] is Reading
    assert call["messages"] == [{"role": "user", "content": "How many A12 this week?"}]


async def test_a_refusal_is_raised_rather_than_treated_as_an_answer():
    messages = _Messages(
        _Response(parsed=Reading(intent="x"), stop_reason="refusal", category="cyber")
    )
    with pytest.raises(LLMRefusalError):
        await _client(messages).structured(system="s", user="u", output_model=Reading)


async def test_missing_structured_output_is_an_error_not_an_empty_reading():
    messages = _Messages(_Response(parsed=None))
    with pytest.raises(LLMError):
        await _client(messages).structured(system="s", user="u", output_model=Reading)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (anthropic.AuthenticationError.__new__(anthropic.AuthenticationError), LLMUnavailableError),
        (anthropic.NotFoundError.__new__(anthropic.NotFoundError), LLMUnavailableError),
        (anthropic.RateLimitError.__new__(anthropic.RateLimitError), LLMError),
        (anthropic.APIConnectionError.__new__(anthropic.APIConnectionError), LLMUnavailableError),
    ],
)
async def test_provider_failures_become_typed_errors(error, expected):
    with pytest.raises(expected):
        await _client(_Messages(error=error)).structured(system="s", user="u", output_model=Reading)


def test_strict_schema_closes_every_object():
    class Nested(BaseModel):
        a: str

    class Outer(BaseModel):
        nested: Nested
        items: list[Nested] = []

    schema = strict_json_schema(Outer)
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["Nested"]["additionalProperties"] is False


# ------------------------------------------------------------------- factory


def test_the_shipped_default_provider_is_the_local_model():
    """Local-first: the factory's production environment is isolated.

    Checks the shipped defaults rather than a live Settings(), which the test
    environment deliberately overrides to run without any model.
    """
    fields = Settings.model_fields
    assert fields["llm_provider"].default == "openai_compatible"
    assert fields["llm_base_url"].default.startswith("http://")
    assert fields["llm_temperature"].default == 0.0, (
        "a small local model is far more consistent at 0"
    )
    assert fields["llm_warmup"].default is True


def test_no_provider_configured_is_a_supported_state():
    client, reason = build_llm_client(Settings(llm_provider="none"))
    assert client is None and "deterministic" in reason


def test_anthropic_without_credentials_degrades_instead_of_failing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    client, reason = build_llm_client(Settings(llm_provider="anthropic", anthropic_api_key=""))
    assert client is None
    assert "no credentials" in reason


def test_anthropic_with_a_key_builds_a_client():
    client, reason = build_llm_client(
        Settings(llm_provider="anthropic", anthropic_api_key="test", llm_model="claude-opus-5")
    )
    assert client is not None and client.name == "anthropic"
    assert client.model == "claude-opus-5"


def test_the_on_premises_provider_needs_a_base_url():
    client, reason = build_llm_client(Settings(llm_provider="openai_compatible", llm_base_url=""))
    assert client is None and "LLM_BASE_URL" in reason

    client, _ = build_llm_client(
        Settings(llm_provider="openai_compatible", llm_base_url="http://localhost:11434/v1")
    )
    assert client is not None and client.name == "openai_compatible"


def test_an_unknown_provider_degrades_rather_than_crashing():
    client, reason = build_llm_client(Settings(llm_provider="gpt-9000"))
    assert client is None and "Unknown LLM_PROVIDER" in reason


def test_the_anthropic_reference_uses_a_current_model_id():
    """The development reference must not carry a retired id — that would fail
    only at the first live call."""
    client, _ = build_llm_client(
        Settings(llm_provider="anthropic", anthropic_api_key="test", llm_model="claude-opus-5")
    )
    assert client.model in {
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-haiku-4-5",
        "claude-fable-5-1",
    }


def test_the_anthropic_path_degrades_if_its_sdk_is_absent(monkeypatch):
    """It is an optional dependency: the deployment ships the local path only."""
    import builtins

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name.startswith("app.llm.anthropic_client"):
            raise ImportError("no anthropic sdk")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    client, reason = build_llm_client(Settings(llm_provider="anthropic", anthropic_api_key="k"))
    assert client is None and "anthropic SDK is not installed" in reason
