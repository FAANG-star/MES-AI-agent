"""Industrial-domain restriction (FR-9).

The guard runs first, before rewriting, before intent extraction, before any
database access. A rejected request must leave no trace in the factory: zero
tool calls, zero MES reads.

Three-stage decision, cheapest first:

  1. **Deny phrases with no in-domain signal** — "write me a story" is settled
     without a model call. Note the ordering: a denial only stands when nothing
     in the sentence is industrial, so "write a report on CNC-03 downtime"
     survives, while "write me a story" does not.
  2. **In-domain vocabulary or an entity id** — accepted outright.
  3. **Neither** — ask the model, if one is available. If none is, the guard
     **fails closed** and rejects. Refusing an occasional legitimate question is
     the right trade for a system that must never answer off-topic requests in
     front of a factory manager.
"""

from __future__ import annotations

import logging

from app.agent.schemas import DomainClassification, GuardVerdict
from app.agent.vocabulary import find_domain_signals, find_out_of_domain_phrases
from app.llm.base import LLMClient, LLMError

log = logging.getLogger(__name__)

REJECTION_MESSAGE = (
    "This AI assistant is restricted to Smart Factory, CNC, manufacturing and MES-related requests."
)

_GUARD_SYSTEM = """You are the domain filter for a CNC factory's MES assistant.

Decide whether a request belongs to the industrial domain: CNC machines, parts and \
production, capacity and scheduling, maintenance and machine condition, materials and \
inventory, production orders and history, or the MES system itself.

Anything else — creative writing, general knowledge, cooking, weather, translation, \
entertainment, personal advice, programming help — is out of domain, even when it is \
phrased politely or mentions a factory in passing.

Judge the request itself, not the words it happens to contain."""


class DomainGuard:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self._llm = llm

    async def check(self, question: str) -> GuardVerdict:
        text = question.strip()
        if not text:
            return GuardVerdict(
                in_domain=False,
                decided_by="fail_closed",
                reason="The request is empty.",
            )

        domain_signals = find_domain_signals(text)
        deny_phrases = find_out_of_domain_phrases(text)

        if deny_phrases and not domain_signals:
            return GuardVerdict(
                in_domain=False,
                decided_by="denylist",
                reason=(
                    f"The request is about {deny_phrases[0]!r}, which is outside "
                    "the factory domain."
                ),
                matched_signals=deny_phrases,
            )

        if domain_signals:
            return GuardVerdict(
                in_domain=True,
                decided_by="allowlist",
                reason="The request uses factory vocabulary or names a factory entity.",
                matched_signals=domain_signals[:6],
            )

        if self._llm is not None:
            try:
                verdict, _ = await self._llm.structured(
                    system=_GUARD_SYSTEM,
                    user=f"Request: {text}",
                    output_model=DomainClassification,
                    max_tokens=256,
                )
                return GuardVerdict(
                    in_domain=verdict.in_domain,
                    decided_by="llm",
                    reason=verdict.reason,
                )
            except LLMError as exc:
                log.warning("Domain guard could not reach the model, failing closed: %s", exc)

        return GuardVerdict(
            in_domain=False,
            decided_by="fail_closed",
            reason=(
                "The request contains no recognisable factory subject, and no language model was "
                "available to judge it. The guard fails closed."
            ),
        )
