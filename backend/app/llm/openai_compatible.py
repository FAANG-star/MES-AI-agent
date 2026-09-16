"""The primary provider: a locally deployed open-weight model.

The factory's production environment is isolated, so the prototype's language
model runs inside the application environment too — Ollama, vLLM or llama.cpp
behind an OpenAI-compatible `/v1/chat/completions` endpoint. Factory questions
and MES data never leave the network.

This is plain HTTP on purpose. It adds no vendor SDK to the deployment, and the
OpenAI-compatible shape is the one every local serving stack exposes.

**Structured output is the hard part**, and it is what this module is mostly
about. Hosted models constrain output to a JSON schema natively; local stacks
vary — some accept a full `json_schema`, some only "must be JSON", some neither,
and a 7B–14B model will occasionally wrap its JSON in prose or code fences
regardless. Since every LLM step in this system extracts into a Pydantic model,
unreliable structured output would break the agent rather than merely degrade it.

So the client negotiates, in order:

  1. `response_format: json_schema`  — strict, the server enforces the shape
  2. `response_format: json_object`  — server guarantees JSON; the schema is
                                       carried in the prompt
  3. prompt-only                     — schema and instruction in the system
                                       prompt, JSON extracted from the reply

It settles on the best mode the endpoint accepts and remembers it. If a reply
still fails validation, it sends the validation error back once and asks for a
correction. Only after that does it raise — at which point the agent falls back
to deterministic understanding, which is why a weaker model degrades the
prototype's flexibility rather than stopping it.

This is not a Claude client and must never be given Anthropic SDK calls; the
Claude path lives in `anthropic_client.py` and uses the official SDK.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.llm.base import LLMClient, LLMError, LLMUnavailableError, LLMUsage, strict_json_schema

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Best to worst. The client walks down this list once per process.
STRUCTURED_MODES = ("json_schema", "json_object", "prompt")

_JSON_INSTRUCTION = (
    "Reply with a single JSON object and nothing else — no explanation, no markdown "
    "code fence. It must validate against this JSON schema:\n\n{schema}"
)


class OpenAICompatibleLLMClient(LLMClient):
    name = "openai_compatible"

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str | None = None,
        timeout_s: float = 60.0,
        temperature: float = 0.0,
        structured_mode: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        # Local runtimes accept a sampling temperature and 0 makes a small model
        # far more consistent. (Current hosted Claude models reject the
        # parameter outright, which is why it lives only on this provider.)
        self.temperature = temperature
        self._mode = structured_mode  # None = negotiate on first use
        headers = {"content-type": "application/json"}
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"
        # A generous read timeout (a 14B model on CPU is slow) but a short
        # connect timeout, so an endpoint that is simply not running fails in
        # seconds rather than stalling the request.
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_s, connect=5.0),
            headers=headers,
            transport=transport,
        )

    @property
    def structured_mode(self) -> str | None:
        """Whichever mode the endpoint turned out to support."""
        return self._mode

    # ------------------------------------------------------------------ public

    async def structured(
        self, *, system: str, user: str, output_model: type[T], max_tokens: int = 2048
    ) -> tuple[T, LLMUsage]:
        schema = strict_json_schema(output_model)
        modes = (
            STRUCTURED_MODES[STRUCTURED_MODES.index(self._mode) :]
            if self._mode
            else STRUCTURED_MODES
        )

        last_error: Exception | None = None
        for mode in modes:
            try:
                text, usage = await self._chat(
                    system=self._system_for(system, mode, schema),
                    user=user,
                    max_tokens=max_tokens,
                    response_format=self._response_format(mode, schema, output_model),
                )
            except _UnsupportedResponseFormat as exc:
                log.info("Endpoint rejected %s mode (%s); trying the next one.", mode, exc)
                last_error = exc
                continue

            if self._mode != mode:
                log.info("Structured output mode for %s: %s", self.model, mode)
                self._mode = mode

            try:
                return output_model.model_validate(_extract_json(text)), usage
            except (ValueError, ValidationError) as exc:
                # One repair attempt: small models often get the shape right on
                # a second pass when told exactly what was wrong.
                log.info("Repairing malformed structured output from %s: %s", self.model, exc)
                repaired, repair_usage = await self._chat(
                    system=self._system_for(system, mode, schema),
                    user=(
                        f"{user}\n\nYour previous reply could not be used:\n{text}\n\n"
                        f"It failed validation with: {exc}\n\n"
                        "Reply again with only the corrected JSON object."
                    ),
                    max_tokens=max_tokens,
                    response_format=self._response_format(mode, schema, output_model),
                )
                usage.output_tokens += repair_usage.output_tokens
                usage.input_tokens += repair_usage.input_tokens
                usage.notes.append("structured output required one repair attempt")
                try:
                    return output_model.model_validate(_extract_json(repaired)), usage
                except (ValueError, ValidationError) as exc2:
                    raise LLMError(
                        f"{self.model} did not return output matching {output_model.__name__} "
                        f"after a repair attempt: {exc2}"
                    ) from exc2

        raise LLMError(
            f"The endpoint at {self.base_url} accepted none of the structured-output modes "
            f"({', '.join(STRUCTURED_MODES)}): {last_error}"
        )

    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 1024,
        temperature: float | None = None,
    ) -> tuple[str, LLMUsage]:
        """Plain text — used by the explainer, on the same local model.

        The temperature is per call. Extraction runs at 0, because the same
        question must yield the same typed reading; the answer does not, because
        greedy decoding over an identical fact sheet writes an identical
        sentence, and a screen full of identical sentences reads as canned.
        """
        return await self._chat(
            system=system,
            user=user,
            max_tokens=max_tokens,
            response_format=None,
            temperature=temperature,
        )

    async def probe(self) -> dict:
        """Is the endpoint up, and does it have the configured model?"""
        try:
            response = await self._http.get(f"{self.base_url}/models")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMUnavailableError(f"Could not reach {self.base_url}: {exc}") from exc
        body = response.json()
        available = [m.get("id") for m in body.get("data", []) if isinstance(m, dict)]
        return {"reachable": True, "models": available, "model_present": self.model in available}

    # --------------------------------------------------------------- internals

    def _system_for(self, system: str, mode: str, schema: dict) -> str:
        if mode == "json_schema":
            return system
        return f"{system}\n\n" + _JSON_INSTRUCTION.format(schema=json.dumps(schema, indent=2))

    def _response_format(
        self, mode: str, schema: dict, output_model: type[BaseModel]
    ) -> dict | None:
        if mode == "json_schema":
            return {
                "type": "json_schema",
                "json_schema": {"name": output_model.__name__, "strict": True, "schema": schema},
            }
        if mode == "json_object":
            return {"type": "json_object"}
        return None

    async def _chat(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int,
        response_format: dict | None,
        temperature: float | None = None,
    ) -> tuple[str, LLMUsage]:
        payload: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": self.temperature if temperature is None else temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if response_format is not None:
            payload["response_format"] = response_format

        started = time.perf_counter()
        try:
            response = await self._http.post(f"{self.base_url}/chat/completions", json=payload)
        except httpx.HTTPError as exc:
            raise LLMUnavailableError(
                f"Could not reach the local model at {self.base_url}: {exc}"
            ) from exc

        if response.status_code >= 400:
            body = response.text[:400]
            if response_format is not None and _looks_like_format_rejection(
                response.status_code, body
            ):
                raise _UnsupportedResponseFormat(body)
            raise LLMError(f"Local model returned {response.status_code}: {body}")

        try:
            body = response.json()
            text = body["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unexpected response shape from {self.base_url}: {exc}") from exc

        usage_body = body.get("usage") or {}
        return text or "", LLMUsage(
            provider=self.name,
            model=body.get("model", self.model),
            input_tokens=usage_body.get("prompt_tokens", 0) or 0,
            output_tokens=usage_body.get("completion_tokens", 0) or 0,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )

    async def aclose(self) -> None:
        await self._http.aclose()


class _UnsupportedResponseFormat(Exception):
    """The endpoint does not support the structured-output mode that was tried."""


def _looks_like_format_rejection(status: int, body: str) -> bool:
    """Tell 'I don't support this option' apart from a genuine failure.

    Serving stacks disagree on both status code and wording, so this matches on
    the option's name appearing in a client error.
    """
    if status not in (400, 404, 415, 422, 500, 501):
        return False
    lowered = body.lower()
    return any(
        term in lowered
        for term in (
            "response_format",
            "json_schema",
            "guided",
            "not supported",
            "unsupported",
            "unknown field",
        )
    )


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _extract_json(text: str) -> dict:
    """Recover the JSON object from a small model's reply.

    Instructed not to, a 7B–14B model may still wrap its answer in a code fence
    or add a sentence before it. Rather than fail on presentation, the object is
    extracted: fenced block first, then the first balanced `{...}` span.
    """
    if not text or not text.strip():
        raise ValueError("the model returned an empty reply")

    candidate = text.strip()
    fenced = _FENCE.search(candidate)
    if fenced:
        candidate = fenced.group(1).strip()

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        parsed = json.loads(_first_json_object(candidate))

    if not isinstance(parsed, dict):
        raise ValueError(f"expected a JSON object, got {type(parsed).__name__}")
    return parsed


def _first_json_object(text: str) -> str:
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object found in the reply")
    depth, in_string, escaped = 0, False, False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ValueError("the JSON object in the reply is not closed")
