"""Provider-neutral LLM interface (ADR-5).

Nothing above this module knows which model is answering. That is what makes the
future on-premises deployment a configuration change rather than a rewrite: the
same agent code runs against a hosted Claude model during development and
against a local open-weight model behind an OpenAI-compatible endpoint in an
air-gapped plant.

The interface is deliberately narrow. The agent needs exactly two things from a
language model:

  * `structured()` — fill in a Pydantic model. Every LLM step in this system is
    an extraction into a typed schema, never free text that later gets parsed.
  * `complete()`   — plain text, used by the explainer.

Neither ever returns a factory number. The model classifies and phrases; the
tools and the calculation engine produce values.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Any failure to obtain a usable answer from the provider."""


class LLMUnavailableError(LLMError):
    """No provider is configured, or it cannot be reached."""


class LLMRefusalError(LLMError):
    """The provider declined to answer. Distinct from a transport failure."""


@dataclass
class LLMUsage:
    """Token accounting, carried into the audit trail."""

    provider: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_ms: int = 0
    notes: list[str] = field(default_factory=list)


class LLMClient(ABC):
    """What the agent may ask of a language model."""

    name: str = "llm"
    model: str = ""

    @abstractmethod
    async def structured(
        self,
        *,
        system: str,
        user: str,
        output_model: type[T],
        max_tokens: int = 2048,
    ) -> tuple[T, LLMUsage]:
        """Return an instance of `output_model`, validated, plus usage."""

    @abstractmethod
    async def complete(
        self, *, system: str, user: str, max_tokens: int = 1024
    ) -> tuple[str, LLMUsage]:
        """Return plain text plus usage."""

    async def aclose(self) -> None:  # pragma: no cover - overridden where needed
        return None


def strict_json_schema(model: type[BaseModel]) -> dict:
    """JSON schema for `model`, tightened for strict structured output.

    Providers that enforce schemas reject free-form keys, so every object needs
    `additionalProperties: false`. Pydantic does not add it, and `$defs` need the
    same treatment, so it is applied recursively.
    """
    schema = model.model_json_schema()

    def tighten(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                node.setdefault("additionalProperties", False)
            for value in node.values():
                tighten(value)
        elif isinstance(node, list):
            for item in node:
                tighten(item)

    tighten(schema)
    return schema
