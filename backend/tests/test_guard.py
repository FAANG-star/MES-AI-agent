"""Industrial-domain restriction (FR-9, scenario R4)."""

from __future__ import annotations

import pytest

from app.agent.guard import REJECTION_MESSAGE, DomainGuard
from app.agent.schemas import DomainClassification
from app.llm.base import LLMClient, LLMError, LLMUsage

FACTORY_QUESTIONS = [
    "How many A12 parts can we produce this week?",
    "Can CNC-03 continue production today?",
    "Which CNC machine is limiting A12 production?",
    "Why was A12 production lower yesterday?",
    "Which machine needs maintenance attention?",
    "Show me CNC-03 status.",
    "How much STEEL-4140 do we have in stock?",
    "What's slowing A12 down?",
    "Maintenance priorities",
]

OFF_TOPIC_QUESTIONS = [
    "Write me a story.",
    "Write a poem about summer.",
    "Tell me a joke",
    "What's the capital of France?",
    "Give me a recipe for carbonara",
    "Translate this into French",
    "What's the weather tomorrow?",
    "What is B12 vitamin good for?",
]


class StubLLM(LLMClient):
    """A model whose answer the test chooses."""

    name = "stub"

    def __init__(self, in_domain: bool = True, fail: bool = False) -> None:
        self.in_domain = in_domain
        self.fail = fail
        self.calls = 0

    async def structured(self, *, system, user, output_model, max_tokens=2048):
        self.calls += 1
        if self.fail:
            raise LLMError("provider down")
        return DomainClassification(in_domain=self.in_domain, reason="stub"), LLMUsage()

    async def complete(self, *, system, user, max_tokens=1024):
        return "", LLMUsage()


@pytest.mark.parametrize("question", FACTORY_QUESTIONS)
async def test_factory_questions_are_accepted(question):
    verdict = await DomainGuard().check(question)
    assert verdict.in_domain, f"{question!r} was rejected: {verdict.reason}"
    assert verdict.matched_signals


@pytest.mark.parametrize("question", OFF_TOPIC_QUESTIONS)
async def test_off_topic_questions_are_rejected(question):
    verdict = await DomainGuard().check(question)
    assert not verdict.in_domain, f"{question!r} was accepted"


async def test_a_factory_request_survives_a_deny_word():
    """'write' alone must not sink a legitimate request."""
    verdict = await DomainGuard().check("Write a report on CNC-03 downtime this week")
    assert verdict.in_domain
    assert verdict.decided_by == "allowlist"


async def test_heuristics_decide_without_calling_the_model():
    llm = StubLLM()
    await DomainGuard(llm).check("How many A12 parts can we produce this week?")
    await DomainGuard(llm).check("Write me a story.")
    assert llm.calls == 0, "clear cases must not cost a model call"


async def test_unclear_requests_go_to_the_model_when_one_exists():
    llm = StubLLM(in_domain=True)
    verdict = await DomainGuard(llm).check("Can you look into the situation from Tuesday?")
    assert llm.calls == 1
    assert verdict.decided_by == "llm" and verdict.in_domain


async def test_guard_fails_closed_without_a_model():
    verdict = await DomainGuard(None).check("Can you look into the situation from Tuesday?")
    assert not verdict.in_domain
    assert verdict.decided_by == "fail_closed"


async def test_guard_fails_closed_when_the_model_errors():
    verdict = await DomainGuard(StubLLM(fail=True)).check("Can you look into that thing?")
    assert not verdict.in_domain
    assert verdict.decided_by == "fail_closed"


async def test_empty_question_is_rejected():
    assert not (await DomainGuard().check("   ")).in_domain


def test_the_rejection_message_is_the_one_the_client_specified():
    assert REJECTION_MESSAGE == (
        "This AI assistant is restricted to Smart Factory, CNC, manufacturing "
        "and MES-related requests."
    )
