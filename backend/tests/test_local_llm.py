"""The local open-weight model path — the primary provider.

Run against a fake OpenAI-compatible server, so the behaviours that actually
break with a small local model are tested without needing one running: an
endpoint that rejects `json_schema`, a model that fences its JSON, a model that
adds a sentence first, and a model that returns the wrong shape until it is told
what was wrong.
"""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel, Field

from app.llm.base import LLMError, LLMUnavailableError
from app.llm.openai_compatible import OpenAICompatibleLLMClient, _extract_json


class Reading(BaseModel):
    intent: str
    confidence: float = Field(default=0.0)


def chat_response(content: str, model: str = "qwen2.5:14b-instruct") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": model,
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 800, "completion_tokens": 120},
        },
    )


class FakeServer:
    """An OpenAI-compatible endpoint whose quirks the test chooses."""

    def __init__(
        self,
        *,
        replies: list[str] | None = None,
        supports: tuple[str, ...] = ("json_schema", "json_object"),
        models: list[str] | None = None,
    ) -> None:
        self.replies = replies or ['{"intent": "production_capacity", "confidence": 0.9}']
        self.supports = supports
        self.models = models if models is not None else ["qwen2.5:14b-instruct"]
        self.requests: list[dict] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": m} for m in self.models]})

        payload = json.loads(request.content)
        self.requests.append(payload)
        fmt = payload.get("response_format")
        if fmt is not None and fmt["type"] not in self.supports:
            return httpx.Response(
                400, json={"error": {"message": f"response_format {fmt['type']} is not supported"}}
            )
        index = min(len(self.requests) - 1, len(self.replies) - 1)
        return chat_response(self.replies[index])


def make_client(server: FakeServer, **kwargs) -> OpenAICompatibleLLMClient:
    return OpenAICompatibleLLMClient(
        model="qwen2.5:14b-instruct",
        base_url="http://localhost:11434/v1",
        transport=server.transport(),
        **kwargs,
    )


# ------------------------------------------------------------------ negotiation


async def test_strict_schema_mode_is_used_when_the_endpoint_supports_it():
    server = FakeServer()
    client = make_client(server)
    reading, usage = await client.structured(system="s", user="u", output_model=Reading)

    assert reading.intent == "production_capacity"
    assert client.structured_mode == "json_schema"
    sent = server.requests[0]["response_format"]
    assert sent["type"] == "json_schema"
    assert sent["json_schema"]["strict"] is True
    assert sent["json_schema"]["schema"]["additionalProperties"] is False
    assert usage.input_tokens == 800


async def test_it_falls_back_to_json_object_when_schema_mode_is_refused():
    """Ollama-style endpoints often accept only 'must be JSON'."""
    server = FakeServer(supports=("json_object",))
    client = make_client(server)
    reading, _ = await client.structured(
        system="Extract the intent.", user="u", output_model=Reading
    )

    assert reading.intent == "production_capacity"
    assert client.structured_mode == "json_object"
    # The schema has to travel in the prompt when the server will not enforce it.
    assert "JSON schema" in server.requests[-1]["messages"][0]["content"]


async def test_it_falls_back_to_prompt_only_when_nothing_is_supported():
    server = FakeServer(supports=())
    client = make_client(server)
    reading, _ = await client.structured(system="Extract.", user="u", output_model=Reading)

    assert reading.intent == "production_capacity"
    assert client.structured_mode == "prompt"
    assert "response_format" not in server.requests[-1]


async def test_the_negotiated_mode_is_reused_and_not_renegotiated():
    server = FakeServer(supports=("json_object",))
    client = make_client(server)
    await client.structured(system="s", user="u", output_model=Reading)
    calls_after_first = len(server.requests)
    await client.structured(system="s", user="u", output_model=Reading)
    assert len(server.requests) == calls_after_first + 1


async def test_a_pinned_mode_skips_negotiation():
    server = FakeServer(supports=("json_schema", "json_object"))
    client = make_client(server, structured_mode="json_object")
    await client.structured(system="s", user="u", output_model=Reading)
    assert server.requests[0]["response_format"]["type"] == "json_object"


# ----------------------------------------------------- small-model sloppiness


@pytest.mark.parametrize(
    "reply",
    [
        '{"intent": "bottleneck", "confidence": 0.7}',
        '```json\n{"intent": "bottleneck", "confidence": 0.7}\n```',
        '```\n{"intent": "bottleneck", "confidence": 0.7}\n```',
        'Sure! Here is the JSON:\n{"intent": "bottleneck", "confidence": 0.7}',
        '{"intent": "bottleneck", "confidence": 0.7}\n\nLet me know if you need more.',
    ],
)
async def test_json_is_recovered_from_however_the_model_presents_it(reply):
    client = make_client(FakeServer(replies=[reply]))
    reading, _ = await client.structured(system="s", user="u", output_model=Reading)
    assert reading.intent == "bottleneck"


async def test_a_bad_shape_is_repaired_on_a_second_attempt():
    server = FakeServer(
        replies=['{"intent": 12345}', '{"intent": "machine_health", "confidence": 0.6}']
    )
    client = make_client(server)
    reading, usage = await client.structured(system="s", user="u", output_model=Reading)

    assert reading.intent == "machine_health"
    assert any("repair" in note for note in usage.notes)
    # The repair prompt must say what was wrong, or the retry is a coin flip.
    assert "failed validation" in server.requests[1]["messages"][1]["content"]


async def test_a_model_that_cannot_produce_the_shape_raises_rather_than_guessing():
    server = FakeServer(replies=["I think the answer is production capacity."])
    with pytest.raises(LLMError, match="after a repair attempt"):
        await make_client(server).structured(system="s", user="u", output_model=Reading)


async def test_an_empty_reply_is_an_error():
    with pytest.raises(LLMError):
        await make_client(FakeServer(replies=[""])).structured(
            system="s", user="u", output_model=Reading
        )


# ------------------------------------------------------------------- mechanics


async def test_temperature_zero_is_sent_for_consistency():
    server = FakeServer()
    await make_client(server, temperature=0.0).structured(
        system="s", user="u", output_model=Reading
    )
    assert server.requests[0]["temperature"] == 0.0


async def test_plain_completion_works_for_the_day_7_explainer():
    server = FakeServer(replies=["CNC-03 is the constraint this week."])
    text, usage = await make_client(server).complete(system="s", user="u")
    assert "CNC-03" in text
    assert usage.provider == "openai_compatible"
    assert "response_format" not in server.requests[0]


async def test_probe_reports_whether_the_model_is_served():
    ok = await make_client(FakeServer()).probe()
    assert ok["reachable"] and ok["model_present"]

    missing = await make_client(FakeServer(models=["llama3.2:1b"])).probe()
    assert missing["reachable"] and not missing["model_present"]
    assert missing["models"] == ["llama3.2:1b"]


async def test_an_unreachable_endpoint_is_reported_as_unavailable():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = OpenAICompatibleLLMClient(
        model="m", base_url="http://localhost:11434/v1", transport=httpx.MockTransport(refuse)
    )
    with pytest.raises(LLMUnavailableError):
        await client.structured(system="s", user="u", output_model=Reading)
    with pytest.raises(LLMUnavailableError):
        await client.probe()


async def test_a_genuine_server_error_is_not_mistaken_for_an_unsupported_option():
    def fail(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": []})
        return httpx.Response(500, json={"error": {"message": "out of memory loading model"}})

    client = OpenAICompatibleLLMClient(
        model="m", base_url="http://x/v1", transport=httpx.MockTransport(fail)
    )
    with pytest.raises(LLMError, match="out of memory"):
        await client.structured(system="s", user="u", output_model=Reading)


def test_json_extraction_rejects_what_is_not_an_object():
    with pytest.raises(ValueError):
        _extract_json("[1, 2, 3]")
    with pytest.raises(ValueError):
        _extract_json("no json here at all")
    with pytest.raises(ValueError):
        _extract_json('{"unclosed": true')
