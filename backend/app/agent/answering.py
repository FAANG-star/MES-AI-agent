"""Steps 7 and 8: write the answer, then prove it is grounded (FR-7).

The order matters. The model writes last, and its output is checked before
anyone sees it — so the language model is the final *phrasing* step, never the
final *authority*.

    deterministic answer  ← already assembled from tool output (Day 5)
        │
        ├─▶ explain        the model rewrites it from a fact sheet
        ├─▶ validate       every number must exist in the retrieved data
        ├─▶ retry once     with the offending tokens named
        └─▶ fall back      to the deterministic answer if it still fails

The fallback is what makes the feature safe to demo. The worst outcome is a
plainer answer, never a wrong one — and the run says which one you are looking
at, through `answer_is_generated` and `validation`.
"""

from __future__ import annotations

import logging
import time

from app.agent.explainer import explain, should_explain
from app.agent.schemas import AgentRun, ExecutedStep, StepStatus, Validation
from app.agent.validator import validate_answer
from app.llm.base import LLMClient, LLMError

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 2  # the draft, then one correction (FR-7: "regenerated once")


async def write_and_validate(run: AgentRun, llm: LLMClient | None) -> list[ExecutedStep]:
    """Produce the final answer and the validation verdict. Returns trace steps."""
    steps: list[ExecutedStep] = []
    deterministic = run.answer

    # An out-of-domain rejection and a clarifying question carry no factory data
    # at all — their wording is fixed by requirement. Validating a constant would
    # be theatre, and adding a step to the trace would spoil the evidence that a
    # rejected request touched nothing (acceptance criterion 7). The verdict is
    # still recorded so every run carries one.
    if not should_explain(run):
        run.validation = Validation(
            grounded=True,
            retries=0,
            note="Fixed wording with no factory data; nothing to ground.",
        )
        return steps

    if llm is None:
        # No model, or an outcome whose wording is fixed by requirement. The
        # deterministic answer still gets checked — a validator that is only
        # exercised on the model's output is a validator nobody trusts.
        # The deterministic answer is checked too. A validator exercised only on
        # the model's output is a validator nobody has reason to trust.
        report = validate_answer(run.answer, run)
        run.validation = Validation(
            grounded=report.grounded,
            retries=0,
            note=f"{report.note} No model was available, so the data-only answer was used.",
        )
        steps.append(_validation_step(run, report, position=len(run.steps) + 1))
        return steps

    attempt = 0
    correction: str | None = None
    draft = ""
    last_report = None

    while attempt < MAX_ATTEMPTS:
        attempt += 1
        started = time.perf_counter()
        try:
            draft, usage = await explain(run, llm, correction=correction)
        except LLMError as exc:
            log.warning("Explanation failed (%s); keeping the deterministic answer.", exc)
            run.notes.append(
                f"The model could not write the answer ({exc}); data-only answer used."
            )
            run.answer = deterministic
            run.answer_is_generated = False
            report = validate_answer(run.answer, run)
            run.validation = Validation(
                grounded=report.grounded, retries=attempt - 1, note="Model unavailable."
            )
            steps.append(_validation_step(run, report, position=len(run.steps) + 1))
            return steps

        steps.append(
            ExecutedStep(
                step=len(run.steps) + len(steps) + 1,
                tool="explainer",
                kind="llm",
                title="Write the answer" if attempt == 1 else "Rewrite the answer",
                status=StepStatus.OK,
                summary=f"{len(draft.split())} words drafted from the fact sheet.",
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                note=(
                    "The model phrases the result; it is given the figures and may not "
                    "produce new ones."
                ),
            )
        )

        last_report = validate_answer(draft, run)
        if last_report.grounded:
            run.answer = draft
            run.answer_is_generated = True
            run.validation = Validation(grounded=True, retries=attempt - 1, note=last_report.note)
            steps.append(
                _validation_step(run, last_report, position=len(run.steps) + len(steps) + 1)
            )
            return steps

        log.info("Answer rejected on attempt %s: %s", attempt, last_report.feedback())
        correction = last_report.feedback()

    # Two attempts, still ungrounded: fall back rather than ship a wrong figure.
    run.answer = deterministic
    run.answer_is_generated = False
    run.notes.append(
        "The model's wording was rejected because it contained figures the factory data "
        "does not support; the data-only answer is shown instead."
    )
    final = validate_answer(run.answer, run)
    run.validation = Validation(
        grounded=final.grounded,
        retries=MAX_ATTEMPTS - 1,
        note=(
            f"Rejected after {MAX_ATTEMPTS} attempts — "
            f"{last_report.feedback() if last_report else 'ungrounded'}. "
            "Fell back to the data-only answer."
        ),
    )
    steps.append(_validation_step(run, final, position=len(run.steps) + len(steps) + 1))
    return steps


def _validation_step(run: AgentRun, report, *, position: int) -> ExecutedStep:
    return ExecutedStep(
        step=position,
        tool="grounding_validator",
        kind="engine",
        title="Check every number against the retrieved data",
        status=StepStatus.OK,
        summary=(
            f"{report.numbers_checked} number(s) and {report.entities_checked} entity "
            f"reference(s) verified."
            if report.grounded
            else f"Rejected: {report.feedback()}"
        ),
        note="Deterministic; no language model is involved in this step.",
    )
