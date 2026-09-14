"""Understanding: question in, understood request and executable plan out.

    question
      → domain guard        reject non-factory requests before anything is read
      → rewrite + intent    one structured model call, or deterministic rules
      → entity resolution   check ids against the real MES
      → tool selection      an ordered plan with declared argument bindings

Nothing is executed here and no factory answer is produced. The executor runs the plan;
the engine computes the numbers; the reliability layer validates and explains. Keeping understanding
separate from execution is what lets the UI show the plan *before* the work
happens — the "AI Analysis Steps" the factory manager watches.

Three outcomes, all first-class: `understood` with a plan, `clarify` with one
question and concrete options, or `rejected_out_of_domain`.
"""

from __future__ import annotations

import logging
import time

from app.agent.entities import EntityResolver
from app.agent.extractor import IntentExtractor
from app.agent.guard import REJECTION_MESSAGE, DomainGuard
from app.agent.schemas import (
    Clarification,
    Intent,
    Understanding,
    UnderstandingStatus,
)
from app.agent.selector import build_plan, missing_requirement, unused_proposals
from app.agent.vocabulary import CAPABILITY_OPTIONS
from app.llm.base import LLMClient
from app.repositories.mes_repository import MesRepository
from app.timewindow import FactoryClock, WindowError, resolve_window

log = logging.getLogger(__name__)


class UnderstandingPipeline:
    def __init__(
        self,
        *,
        repo: MesRepository,
        clock: FactoryClock,
        llm: LLMClient | None = None,
        provider_name: str = "none",
    ) -> None:
        self._repo = repo
        self._clock = clock
        self._llm = llm
        self._provider = provider_name
        self._guard = DomainGuard(llm)
        self._extractor = IntentExtractor(llm)
        self._resolver = EntityResolver(repo)

    async def understand(self, question: str) -> Understanding:
        started = time.perf_counter()
        degraded = self._llm is None

        # 1. Domain restriction, before any factory data is touched.
        verdict = await self._guard.check(question)
        if not verdict.in_domain:
            return self._finish(
                Understanding(
                    status=UnderstandingStatus.REJECTED_OUT_OF_DOMAIN,
                    question=question,
                    rejection=REJECTION_MESSAGE,
                    guard=verdict,
                    provider=self._provider,
                    degraded=degraded,
                    understood_by="rules" if verdict.decided_by != "llm" else "llm",
                ),
                started,
            )

        # 2. Rewrite and structured intent, in one pass.
        extracted, path, _usage, notes = await self._extractor.extract(question)
        degraded = degraded or path == "rules"

        understanding = Understanding(
            status=UnderstandingStatus.UNDERSTOOD,
            question=question,
            rewritten_question=extracted.rewritten_question,
            intent=extracted.intent,
            metric=extracted.metric,
            confidence=extracted.confidence,
            guard=verdict,
            understood_by=path,
            provider=self._provider if path == "llm" else "none",
            degraded=degraded,
            notes=list(notes),
        )

        # 3. The window, resolved to concrete factory-local dates.
        try:
            understanding.window = resolve_window(extracted.time_window, self._clock)
        except WindowError as exc:
            understanding.notes.append(f"{exc} Falling back to the current week.")
            understanding.window = resolve_window("this_week", self._clock)

        if extracted.ambiguous:
            return self._finish(self._as_clarification(understanding, extracted), started)

        # 4. Entities, checked against the MES rather than trusted.
        understanding.entities = await self._resolver.resolve(
            part_ids=extracted.part_ids,
            machine_ids=extracted.machine_ids,
            material_ids=extracted.material_ids,
        )
        for unknown in understanding.entities.unknown:
            understanding.notes.append(
                f"{unknown.id} does not exist in the MES; the answer will say so "
                "rather than invent it."
            )

        # An intent that needs a part, with no known part, cannot be planned.
        missing = missing_requirement(understanding.intent, understanding.entities)
        if missing == "part":
            return self._finish(
                self._missing_part_clarification(understanding),
                started,
            )

        # 5. The plan.
        understanding.plan = build_plan(
            intent=understanding.intent,
            entities=understanding.entities,
            time_window=extracted.time_window,
        )
        unused = unused_proposals(understanding.plan, extracted.required_tools)
        if unused:
            understanding.notes.append(
                f"The model also proposed {', '.join(unused)}; not run, because nothing in "
                "this answer uses it."
            )
        if not understanding.plan:
            return self._finish(self._as_clarification(understanding, extracted), started)

        return self._finish(understanding, started)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _as_clarification(understanding: Understanding, extracted) -> Understanding:
        understanding.status = UnderstandingStatus.CLARIFY
        options = extracted.clarification_options or list(
            _DEFAULT_OPTIONS.get(understanding.intent, CAPABILITY_OPTIONS)
        )
        reason = extracted.ambiguity_reason or "The request could be read in more than one way."
        understanding.clarification = Clarification(
            question=_clarifying_question(understanding.intent, options),
            options=options,
            because=reason,
        )
        understanding.plan = []
        return understanding

    @staticmethod
    def _missing_part_clarification(understanding: Understanding) -> Understanding:
        known = ", ".join(understanding.entities.known_part_ids)
        understanding.status = UnderstandingStatus.CLARIFY
        understanding.clarification = Clarification(
            question=f"Which part do you mean? The factory currently produces {known}.",
            options=understanding.entities.known_part_ids,
            because="This question is about a specific part, but none was named.",
        )
        understanding.plan = []
        return understanding

    @staticmethod
    def _finish(understanding: Understanding, started: float) -> Understanding:
        understanding.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return understanding


# When the request names a quantity but not which one, these are the readings.
_QUANTITY_OPTIONS: tuple[str, ...] = (
    "Maximum production capacity",
    "Planned production quantity",
    "Actual production quantity",
)

_DEFAULT_OPTIONS: dict[Intent, tuple[str, ...]] = {
    Intent.PRODUCTION_CAPACITY: _QUANTITY_OPTIONS,
    Intent.PRODUCTION_ORDERS: _QUANTITY_OPTIONS,
}


def _clarifying_question(intent: Intent, options: list[str]) -> str:
    """One question, with the concrete readings spelled out (FR-2)."""
    if intent is Intent.UNKNOWN:
        return "I could not tell what you are asking about. Which of these do you need?"
    if intent is Intent.PRODUCTION_CAPACITY:
        return (
            "Do you mean maximum production capacity, planned production, or actual production "
            "— and for which period?"
        )
    joined = ", ".join(options[:-1]) + f", or {options[-1]}" if len(options) > 1 else options[0]
    return f"Could you confirm what you need: {joined}?"
