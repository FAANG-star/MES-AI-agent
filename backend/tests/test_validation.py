"""Grounding validation and explanation (FR-7, acceptance criterion 5).

The central test is the one that proves the safeguard fires: a draft answer
containing a plausible, well-formed, invented number must be rejected. That is
not hypothetical — it is what both local models did on Day 4 when asked to
explain a capacity result.
"""

from __future__ import annotations

import pytest

from app.agent.answering import write_and_validate
from app.agent.explainer import build_fact_sheet, should_explain
from app.agent.pipeline import AgentPipeline
from app.agent.schemas import RunStatus, StepStatus
from app.agent.validator import GroundingReport, validate_answer
from app.llm.base import LLMClient, LLMError, LLMUsage
from tests.conftest import requires_db

pytestmark = requires_db


class ScriptedExplainer(LLMClient):
    """A model that says exactly what the test tells it to, in order."""

    name = "scripted"

    def __init__(self, *drafts: str, fail: bool = False) -> None:
        self._drafts = list(drafts)
        self._fail = fail
        self.calls: list[str] = []

    async def complete(self, *, system, user, max_tokens=1024):
        self.calls.append(user)
        if self._fail:
            raise LLMError("model unreachable")
        draft = self._drafts[min(len(self.calls) - 1, len(self._drafts) - 1)]
        return draft, LLMUsage(provider=self.name)

    async def structured(self, *, system, user, output_model, max_tokens=2048):  # pragma: no cover
        raise NotImplementedError


@pytest.fixture
def agent(repo, ctx):
    return AgentPipeline(repo=repo, clock=ctx.clock, llm=None, provider_name="none")


@pytest.fixture
async def capacity_run(agent):
    return await agent.ask("How many A12 parts can we produce this week?")


# ------------------------------------------------------------ the validator


async def test_the_deterministic_answer_is_grounded(capacity_run):
    """The validator must not cry wolf on an answer built from tool output."""
    report = validate_answer(capacity_run.answer, capacity_run)
    assert report.grounded, report.feedback()
    assert report.numbers_checked > 0


async def test_an_invented_number_is_rejected(capacity_run):
    """The Day-4 failure, reproduced: correct figures plus one fabricated one."""
    capacity = capacity_run.capacity.final_capacity
    draft = (
        f"The maximum A12 capacity this week is {capacity} units. CNC-03 is the "
        "constraint, and there are 28 hours remaining."
    )
    report = validate_answer(draft, capacity_run)
    assert not report.grounded
    assert "28" in report.unsupported_numbers
    assert "28" in report.feedback()


async def test_a_machine_that_does_not_exist_is_rejected(capacity_run):
    report = validate_answer("CNC-09 is the bottleneck this week.", capacity_run)
    assert not report.grounded
    assert report.unsupported_entities == ["CNC-09"]


async def test_thousands_separators_and_rounding_are_accepted(capacity_run):
    capacity = capacity_run.capacity.final_capacity
    bottleneck = capacity_run.bottleneck.machine_id
    assert validate_answer(
        f"Capacity is {capacity:,} units, limited by {bottleneck}.", capacity_run
    ).grounded


async def test_identifiers_are_not_read_as_numbers(capacity_run):
    """CNC-03 must not donate a 3, and A12 must not donate a 12."""
    capacity = capacity_run.capacity.final_capacity
    report = validate_answer(
        f"CNC-03 runs A12 using STEEL-4140; capacity is {capacity} units.", capacity_run
    )
    assert report.grounded, report.feedback()
    assert report.entities_checked == 3


async def test_a_fraction_may_be_written_as_a_percentage(agent):
    """The engine stores a relative breach as 0.24; the answer says 24 %."""
    run = await agent.ask("Which machine needs maintenance attention?")
    report = validate_answer("CNC-04 is 24% over its vibration limit.", run)
    assert report.grounded, report.feedback()


async def test_a_count_of_returned_rows_is_grounded(capacity_run):
    """ "3 eligible machines" is in the data even though no field holds a 3."""
    capacity = capacity_run.capacity.final_capacity
    bottleneck = capacity_run.bottleneck.machine_id
    report = validate_answer(
        f"3 machines are eligible, giving {capacity} units; {bottleneck} limits it.",
        capacity_run,
    )
    assert report.grounded, report.feedback()


# --------------------------------------- grounded, but still the wrong answer


async def test_a_grounded_but_wrong_headline_is_rejected(capacity_run):
    """The live failure this check exists for.

    Asked for this week's A12 capacity, the local model answered with one
    machine's contribution instead of the total. Every digit was in the data;
    the answer was false.
    """
    one_machine = next(m.parts_possible for m in capacity_run.capacity.machines if m.eligible)
    assert one_machine != capacity_run.capacity.final_capacity

    report = validate_answer(
        f"This week we can produce up to {one_machine} A12 parts. CNC-03 limits it.",
        capacity_run,
    )
    assert not report.grounded
    assert report.missing_claims, "the total must be stated"
    assert str(capacity_run.capacity.final_capacity) in report.feedback()


async def test_naming_the_wrong_machine_is_rejected(agent):
    """S5 ranked CNC-04 first; the model once answered CNC-01, which is in the data."""
    run = await agent.ask("Which machine needs maintenance attention?")
    assert run.headline.text == "CNC-04"

    report = validate_answer("CNC-01 needs attention, its temperature is 72.5 °C.", run)
    assert not report.grounded
    assert any("CNC-04" in claim for claim in report.missing_claims)


async def test_omitting_the_bottleneck_is_rejected(capacity_run):
    capacity = capacity_run.capacity.final_capacity
    report = validate_answer(f"We can produce {capacity} units this week.", capacity_run)
    assert not report.grounded
    assert any("limiting machine" in claim for claim in report.missing_claims)


async def test_stating_the_finding_passes(capacity_run):
    capacity = capacity_run.capacity.final_capacity
    bottleneck = capacity_run.bottleneck.machine_id
    report = validate_answer(
        f"A12 capacity this week is {capacity:,} units. {bottleneck} is the limiting machine.",
        capacity_run,
    )
    assert report.grounded, report.feedback()


async def test_an_empty_answer_is_not_grounded(capacity_run):
    assert not validate_answer("   ", capacity_run).grounded


async def test_a_date_outside_the_data_is_rejected(capacity_run):
    report = validate_answer("Production resumes on 1999-01-01.", capacity_run)
    assert not report.grounded
    assert report.unsupported_dates == ["1999-01-01"]


# ------------------------------------------------------------- the explainer


async def test_the_fact_sheet_carries_the_numbers_and_nothing_else(capacity_run):
    facts = build_fact_sheet(capacity_run)
    assert str(capacity_run.capacity.final_capacity) in facts
    assert "cycle time" in facts
    assert "binding constraint" in facts
    assert "Retrieved from the MES" in facts


async def test_a_grounded_draft_is_accepted_and_marked_as_generated(repo, ctx, capacity_run):
    capacity = capacity_run.capacity.final_capacity
    llm = ScriptedExplainer(
        f"A12 capacity this week is {capacity} units. "
        f"{capacity_run.bottleneck.machine_id} is the limiting machine."
    )
    steps = await write_and_validate(capacity_run, llm)

    assert capacity_run.answer_is_generated is True
    assert str(capacity) in capacity_run.answer
    assert capacity_run.validation.grounded is True
    assert capacity_run.validation.retries == 0
    assert [s.kind for s in steps] == ["llm", "engine"]


async def test_an_ungrounded_draft_is_retried_once_then_falls_back(capacity_run):
    """FR-7 exactly: regenerate once, then downgrade to a data-only response."""
    deterministic = capacity_run.answer
    llm = ScriptedExplainer(
        "Capacity is 9999 units.",  # invented
        "Actually capacity is 8888 units.",  # invented again
    )
    steps = await write_and_validate(capacity_run, llm)

    assert len(llm.calls) == 2, "one draft, one correction — no more"
    assert "these numbers do not appear" in llm.calls[1], "the retry is told what was wrong"
    assert capacity_run.answer == deterministic, "a wrong number never reaches the user"
    assert capacity_run.answer_is_generated is False
    assert capacity_run.validation.retries == 1
    assert "Fell back to the data-only answer" in capacity_run.validation.note
    assert any("rejected" in n for n in capacity_run.notes)
    assert [s.kind for s in steps] == ["llm", "llm", "engine"]


async def test_a_corrected_second_draft_is_accepted(capacity_run):
    capacity = capacity_run.capacity.final_capacity
    llm = ScriptedExplainer(
        "Capacity is 9999 units.",
        f"Capacity is {capacity} units, limited by {capacity_run.bottleneck.machine_id}.",
    )
    await write_and_validate(capacity_run, llm)

    assert capacity_run.answer_is_generated is True
    assert capacity_run.validation.grounded is True
    assert capacity_run.validation.retries == 1


async def test_a_model_failure_keeps_the_deterministic_answer(capacity_run):
    deterministic = capacity_run.answer
    await write_and_validate(capacity_run, ScriptedExplainer(fail=True))

    assert capacity_run.answer == deterministic
    assert capacity_run.answer_is_generated is False
    assert any("could not write the answer" in n for n in capacity_run.notes)


async def test_fixed_wording_outcomes_are_not_sent_to_the_model(agent, repo, ctx):
    """A rejection and a clarification are already final, and must stay clean."""
    for question in ("Write me a story.", "How many A12?"):
        run = await agent.ask(question)
        llm = ScriptedExplainer("something else entirely")
        steps = await write_and_validate(run, llm)

        assert llm.calls == [], "no model call for a fixed message"
        assert steps == [], "no step, so a rejected run still shows nothing happened"
        assert run.validation.grounded is True
        assert should_explain(run) is False


async def test_a_refusal_is_explained_without_inventing_a_number(agent):
    """The missing-data refusal still goes to the model, but names the field."""
    run = await agent.ask("How many B20 parts can we produce tomorrow?")
    assert run.status is RunStatus.REFUSED_MISSING_DATA
    assert should_explain(run) is True

    llm = ScriptedExplainer(
        "I cannot calculate B20 production capacity because the cycle time is not recorded."
    )
    await write_and_validate(run, llm)
    assert run.validation.grounded is True
    assert "cycle time" in run.answer.lower()
    assert "parts.cycle_time_min" in build_fact_sheet(run)


async def test_the_validation_step_appears_in_the_trace(capacity_run):
    capacity = capacity_run.capacity.final_capacity
    await write_and_validate(
        capacity_run,
        ScriptedExplainer(f"{capacity} units, limited by {capacity_run.bottleneck.machine_id}."),
    )
    check = [s for s in capacity_run.steps if s.tool == "grounding_validator"]
    assert len(check) == 1
    assert check[0].kind == "engine"
    assert check[0].status is StepStatus.OK


def test_the_report_explains_itself_for_the_retry():
    report = GroundingReport(
        grounded=False, unsupported_numbers=["28"], unsupported_entities=["CNC-09"]
    )
    feedback = report.feedback()
    assert "28" in feedback and "CNC-09" in feedback


async def test_a_bottleneck_answer_need_not_repeat_the_capacity_figure(agent):
    """S3 asks which machine limits A12, not how many parts.

    The run still carries the capacity headline — it is what the machines were
    ranked by — but demanding that figure in the prose rejected a correct
    bottleneck answer twice and fell back to the data-only text. The machine is
    the claim that matters here.
    """
    run = await agent.ask("Which CNC machine is limiting A12 production?")
    assert run.headline is not None and run.headline.value is not None

    report = validate_answer(
        f"{run.bottleneck.machine_id} is the limiting machine this week.",
        run,
    )
    assert report.grounded, report.feedback()


# ------------------------------------------- verdict headlines, not phrasings


async def test_a_health_verdict_may_be_worded_freely(agent):
    """The claim is the polarity, not the phrase.

    Requiring the literal headline text "Can continue production" rejected
    "CNC-03 is running normally and is safe to keep in production" twice, and
    the run fell back to the data-only answer — a correct sentence thrown away
    for wording.
    """
    run = await agent.ask("What is the status of CNC-03?")
    assert run.headline.text == "Can continue production"

    report = validate_answer("CNC-03 is running normally and is safe to keep going.", run)
    assert report.grounded, report.feedback()


async def test_an_inverted_health_verdict_is_rejected(agent):
    run = await agent.ask("What is the status of CNC-03?")
    report = validate_answer("CNC-03 cannot continue production.", run)
    assert not report.grounded
    assert any("can continue production" in claim for claim in report.missing_claims)
