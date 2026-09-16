"""Claude provider, via the official Anthropic Python SDK."""

from __future__ import annotations

import logging
import time
from typing import TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from app.llm.base import (
    LLMClient,
    LLMError,
    LLMRefusalError,
    LLMUnavailableError,
    LLMUsage,
    strict_json_schema,
)

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class AnthropicLLMClient(LLMClient):
    """Structured extraction with Claude.

    `messages.parse()` is the primary path: it constrains the response to the
    Pydantic schema and validates it, so a malformed intent object is impossible
    rather than merely unlikely. Should a deployment's SDK not offer it, the
    client falls back to `messages.create()` with an explicit JSON schema, which
    is the same guarantee expressed the longer way.
    """

    name = "anthropic"

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_s: float = 30.0,
        max_retries: int = 2,
    ) -> None:
        self.model = model
        kwargs: dict = {"timeout": timeout_s, "max_retries": max_retries}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        # With no explicit key the SDK still resolves ANTHROPIC_API_KEY,
        # ANTHROPIC_AUTH_TOKEN or an `ant auth login` profile.
        try:
            self._client = anthropic.AsyncAnthropic(**kwargs)
        except Exception as exc:  # pragma: no cover - constructor rarely fails
            raise LLMUnavailableError(f"Could not construct the Anthropic client: {exc}") from exc

    async def structured(
        self, *, system: str, user: str, output_model: type[T], max_tokens: int = 2048
    ) -> tuple[T, LLMUsage]:
        started = time.perf_counter()
        try:
            response = await self._client.messages.parse(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=output_model,
            )
            parsed = response.parsed_output
            if parsed is None:
                raise LLMError("The model returned no parsable structured output.")
        except AttributeError:  # pragma: no cover - only on SDKs without parse()
            parsed, response = await self._structured_via_schema(
                system=system, user=user, output_model=output_model, max_tokens=max_tokens
            )
        except ValidationError as exc:
            raise LLMError(f"Structured output failed schema validation: {exc}") from exc
        except anthropic.APIError as exc:
            raise self._translate(exc) from exc

        self._raise_on_refusal(response)
        return parsed, self._usage(response, started)

    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 1024,
        temperature: float | None = None,
    ) -> tuple[str, LLMUsage]:
        # `temperature` is accepted and not forwarded: current hosted Claude
        # models reject the parameter outright (see the note in factory.py).
        started = time.perf_counter()
        try:
            response = await self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except anthropic.APIError as exc:
            raise self._translate(exc) from exc

        self._raise_on_refusal(response)
        text = "".join(block.text for block in response.content if block.type == "text")
        return text, self._usage(response, started)

    # ------------------------------------------------------------------ internals

    async def _structured_via_schema(self, *, system, user, output_model, max_tokens):
        """Raw-schema equivalent of parse(), for SDKs without the helper."""
        import json

        response = await self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={
                "format": {"type": "json_schema", "schema": strict_json_schema(output_model)}
            },
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        return output_model.model_validate(json.loads(text)), response

    @staticmethod
    def _raise_on_refusal(response) -> None:
        """`stop_reason` must be checked before trusting content."""
        if getattr(response, "stop_reason", None) == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None)
            raise LLMRefusalError(f"The model declined to answer (category: {category}).")

    def _usage(self, response, started: float) -> LLMUsage:
        usage = getattr(response, "usage", None)
        return LLMUsage(
            provider=self.name,
            model=getattr(response, "model", self.model),
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )

    @staticmethod
    def _translate(exc: anthropic.APIError) -> LLMError:
        """Most-specific-first, so retryable and permanent failures stay distinct."""
        if isinstance(exc, anthropic.AuthenticationError):
            return LLMUnavailableError("Anthropic rejected the credentials.")
        if isinstance(exc, anthropic.PermissionDeniedError):
            return LLMUnavailableError("The credentials lack permission for this model.")
        if isinstance(exc, anthropic.NotFoundError):
            return LLMUnavailableError("The configured model does not exist.")
        if isinstance(exc, anthropic.RateLimitError):
            return LLMError("Rate limited by the provider.")
        if isinstance(exc, anthropic.APIConnectionError):
            return LLMUnavailableError("Could not reach the provider.")
        if isinstance(exc, anthropic.APIStatusError):
            return LLMError(f"Provider error {exc.status_code}: {exc.message}")
        return LLMError(str(exc))

    async def aclose(self) -> None:
        await self._client.close()
