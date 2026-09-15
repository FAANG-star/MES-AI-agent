"""Grounding validation and explanation (FR-7, acceptance criterion 5).

The central test is the one that proves the safeguard fires: a draft answer
containing a plausible, well-formed, invented number must be rejected. That is
not hypothetical — it is what both local models did when first asked to
explain a capacity result.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.agent.answering import write_and_validate
from app.agent.explainer import build_fact_sheet, should_explain
from app.agent.pipeline import AgentPipeline
from app.agent.schemas import RunStatus, StepStatus
from app.agent.validator import GroundingReport, allowed_values, validate_answer
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


def finding(run) -> str:
    """A sentence stating whatever this run's principal finding turns out to be.

    The validator requires the finding to be stated, and what the finding *is*
    depends on the factory: on most days one lathe has maintenance and is the
    bottleneck, but in a window holding a single shift the three lathes are
    exactly level and the honest answer says so. A test about grounding should
    not also be a test about which day of the week it is — that distinction is
    `test_engine_oracle.py`'s job.
    """
    parts = []
    if run.headline is not None and run.headline.value is not None:
        parts.append(f"{run.headline.value:g} {run.headline.unit}".strip())
    if run.bottleneck is not None:
        parts.append(f"{run.bottleneck.machine_id} is the limiting machine")
    elif run.constraint is not None and run.constraint.bottleneck is None:
        parts.append("no single machine is the constraint")
    return ". ".join(parts) + "."


# ------------------------------------------------------------ the validator


async def test_the_deterministic_answer_is_grounded(capacity_run):
    """The validator must not cry wolf on an answer built from tool output."""
    report = validate_answer(capacity_run.answer, capacity_run)
    assert report.grounded, report.feedback()
    assert report.numbers_checked > 0


async def test_an_invented_number_is_rejected(capacity_run):
    """The first measured failure, reproduced: correct figures plus one fabricated one."""
    capacity = capacity_run.capacity.final_capacity
    # The live model invented "28 hours". On some days of the week 28 is a real
    # figure in the seeded factory, so the fabricated number is chosen as one
    # the run provably does not contain — the test is about invention, not 28.
    allowed, _ = allowed_values(capacity_run)
    invented = next(n for n in range(23, 1000) if Decimal(n) not in allowed)
    draft = (
        f"The maximum A12 capacity this week is {capacity} units. {finding(capacity_run)} "
        f"There are {invented} hours remaining."
    )
    report = validate_answer(draft, capacity_run)
    assert not report.grounded
    assert str(invented) in report.unsupported_numbers
    assert str(invented) in report.feedback()


async def test_a_machine_that_does_not_exist_is_rejected(capacity_run):
    report = validate_answer("CNC-09 is the bottleneck this week.", capacity_run)
    assert not report.grounded
    assert report.unsupported_entities == ["CNC-09"]


async def test_thousands_separators_and_rounding_are_accepted(capacity_run):
    capacity = capacity_run.capacity.final_capacity
    assert validate_answer(
        f"Capacity is {capacity:,} units. {finding(capacity_run)}", capacity_run
    ).grounded


async def test_identifiers_are_not_read_as_numbers(capacity_run):
    """CNC-03 must not donate a 3, and A12 must not donate a 12."""
    capacity = capacity_run.capacity.final_capacity
    report = validate_answer(
        f"A12 runs on STEEL-4140; capacity is {capacity} units. {finding(capacity_run)}",
        capacity_run,
    )
    assert report.grounded, report.feedback()
    assert report.entities_checked >= 2


async def test_a_fraction_may_be_written_as_a_percentage(agent):
    """The engine stores a relative breach as 0.24; the answer says 24 %."""
    run = await agent.ask("Which machine needs maintenance attention?")
    report = validate_answer("CNC-04 is 24% over its vibration limit.", run)
    assert report.grounded, report.feedback()


async def test_a_count_of_returned_rows_is_grounded(capacity_run):
    """ "3 eligible machines" is in the data even though no field holds a 3."""
    capacity = capacity_run.capacity.final_capacity
    report = validate_answer(
        f"3 machines are eligible, giving {capacity} units. {finding(capacity_run)}",
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
    report = validate_answer(finding(capacity_run), capacity_run)
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
    llm = ScriptedExplainer(f"A12 capacity this week is {finding(capacity_run)}")
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
    llm = ScriptedExplainer(
        "Capacity is 9999 units.",
        f"Capacity is {finding(capacity_run)}",
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
    await write_and_validate(capacity_run, ScriptedExplainer(finding(capacity_run)))
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

    The machine is the claim that matters here: demanding the capacity figure
    in the prose rejected a correct bottleneck answer twice and fell back to
    the data-only text. The headline names the machine, and the capacity the
    machines were ranked by stays on the run for the calculation panel.
    """
    run = await agent.ask("Which CNC machine is limiting A12 production?")
    assert run.bottleneck is not None, "the seeded factory has a bottleneck every day"
    assert run.headline is not None and run.headline.text == run.bottleneck.machine_id
    assert run.headline.value is None, "a bottleneck question is not answered by a quantity"
    assert run.capacity is not None, "the figure it was ranked by is still on the run"

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


# ---------------------------------------------------- a tie is also a finding


def _tie(run):
    """The same run, with the engine having found the eligible machines level.

    The seeded factory has a real bottleneck on every day of the week, so a tie
    is constructed rather than waited for. The validator reads only
    `constraint` and `bottleneck`; everything else stays real.
    """
    from app.engine.bottleneck import ConstraintFinding

    level = [line.machine_id for line in run.capacity.machines if line.eligible]
    hours = min(line.effective_hours for line in run.capacity.machines if line.eligible)
    tied = run.model_copy(deep=True)
    tied.bottleneck = None
    tied.constraint = ConstraintFinding(
        kind="none",
        explanation=f"No single bottleneck: {', '.join(level)} all have {hours:g} available hours.",
        ranking=[],
    )
    return tied, level, hours


async def test_naming_a_bottleneck_when_the_engine_found_none_is_rejected(capacity_run):
    """Found while building the web interface, on a Saturday.

    With the week's remaining window holding one shift, the three eligible
    lathes were exactly level, and the engine reported "No single bottleneck".
    The model answered "CNC-01 has the available hours and the reason is
    material" — grounded, incoherent and wrong. A tie is a finding; an answer
    that quietly picks a winner contradicts it.
    """
    run, level, _ = _tie(capacity_run)
    report = validate_answer(f"{level[0]} is the limiting machine.", run)
    assert not report.grounded
    assert any("no single machine" in claim for claim in report.missing_claims)


async def test_saying_the_machines_are_level_passes(capacity_run):
    run, level, _ = _tie(capacity_run)
    capacity = run.capacity.final_capacity
    report = validate_answer(
        f"We can produce {capacity} units. No single machine is the bottleneck: "
        f"{', '.join(level)} are level.",
        run,
    )
    assert report.grounded, report.feedback()


# ------------------------------------------- which kind of thing is the limit


async def test_blaming_material_when_the_engine_says_machines_is_rejected(capacity_run):
    """From the first screenshot of the finished web interface.

    The answer read: "We can produce up to 411 A12 parts this week. This limit
    is set by the material availability of 9600 units of STEEL-4140…" — while
    the engine had recorded 411 against a material ceiling of 9600, which is
    machine-constrained by a wide margin. Every figure was real; the sentence
    named the wrong constraint.
    """
    assert capacity_run.capacity.binding_constraint == "machine"
    capacity = capacity_run.capacity.final_capacity
    stock = capacity_run.capacity.available_quantity

    report = validate_answer(
        f"We can produce up to {capacity} units. This limit is set by the material "
        f"availability of {stock:g} units of STEEL-4140.",
        capacity_run,
    )
    assert not report.grounded
    assert any("machine-constrained" in claim for claim in report.missing_claims)


async def test_naming_machine_hours_as_the_limit_passes(capacity_run):
    assert capacity_run.capacity.binding_constraint == "machine"
    report = validate_answer(
        f"{finding(capacity_run)} It is limited by the available machine hours.",
        capacity_run,
    )
    assert report.grounded, report.feedback()


async def test_material_mentioned_without_being_blamed_is_fine(capacity_run):
    """The check reads the clause after the limit phrase, not the sentence.

    "Limited by machine hours; material stock is ample" names both, and only
    one of them as the constraint.
    """
    report = validate_answer(
        f"{finding(capacity_run)} Limited by machine hours; material stock is ample.",
        capacity_run,
    )
    assert report.grounded, report.feedback()


async def test_the_material_branch_is_checked_the_same_way(agent):
    """C15 is the material-constrained part, so the blame runs the other way."""
    run = await agent.ask("How many C15 parts can we produce this week?")
    assert run.capacity is not None and run.capacity.binding_constraint == "material"

    report = validate_answer(
        f"We can produce {run.capacity.final_capacity} units, limited by the available "
        "machine hours.",
        run,
    )
    assert not report.grounded
    assert any("material-constrained" in claim for claim in report.missing_claims)


# ----------------------- contradictions from the live scenario matrix


@pytest.fixture
async def bottleneck_run(agent):
    return await agent.ask("Which CNC machine is limiting A12 production?")


@pytest.fixture
async def analysis_run(agent):
    return await agent.ask("Why was A12 production lower yesterday?")


async def test_hours_called_units_are_rejected(bottleneck_run):
    """Live: "CNC-03 has 32 available hours and is the reason for the 32
    available units of A12 production." — 32 was hours both times."""
    hours = bottleneck_run.constraint.bottleneck.effective_hours
    report = validate_answer(
        f"CNC-03 has {hours:g} available hours and is the reason for the {hours:g} "
        "available units of A12 production.",
        bottleneck_run,
    )
    assert not report.grounded
    assert any("in hours, not units" in claim for claim in report.wrong_claims)


async def test_hours_called_shifts_are_rejected(bottleneck_run):
    """Live: "it has only 56 planned shifts against 112" — both were hours."""
    others = max(
        line.planned_hours
        for line in bottleneck_run.capacity.machines
        if line.machine_id != "CNC-03" and line.eligible
    )
    report = validate_answer(
        f"CNC-03 is the limiting machine; the others have {others:g} planned shifts.",
        bottleneck_run,
    )
    assert any("not a number of shifts" in claim for claim in report.wrong_claims)


async def test_one_machines_share_presented_as_the_limit_is_rejected(bottleneck_run):
    """Live: "production is limited to 548 units this week" — CNC-03's share."""
    share = bottleneck_run.constraint.bottleneck.parts_possible
    report = validate_answer(
        f"CNC-03 is the reason A12 production is limited to {share} units this week.",
        bottleneck_run,
    )
    assert not report.grounded
    assert any("not the total" in claim for claim in report.wrong_claims)


async def test_the_real_total_may_be_stated_as_the_limit(capacity_run):
    report = validate_answer(
        f"We can produce up to {capacity_run.capacity.final_capacity} A12 parts this week. "
        f"{finding(capacity_run)}",
        capacity_run,
    )
    assert report.grounded, report.feedback()


async def test_maintenance_called_active_on_a_machine_cleared_to_run_is_rejected(agent):
    """Live: "CNC-03 can continue production. Maintenance is active for 24 hours." """
    run = await agent.ask("Can CNC-03 continue production today?")
    report = validate_answer("CNC-03 can continue production. Maintenance is active.", run)
    assert not report.grounded
    assert any("no maintenance is active on CNC-03" in claim for claim in report.wrong_claims)


async def test_saying_no_maintenance_is_active_passes(agent):
    run = await agent.ask("Can CNC-03 continue production today?")
    report = validate_answer("CNC-03 can continue production. No maintenance is active.", run)
    assert report.grounded, report.feedback()


async def test_rejects_attributed_to_one_machine_are_rejected(analysis_run):
    """Live: "The secondary factor was the 8 parts rejected at CNC-03." — the 8
    rejects were 3 + 3 + 2 across three machines."""
    total = analysis_run.analysis.rejected_quantity
    report = validate_answer(
        f"A12 production was {analysis_run.analysis.pct_below_plan:g}% below plan. "
        f"The secondary factor was the {total} parts rejected at CNC-03.",
        analysis_run,
    )
    assert any("not CNC-03 alone" in claim for claim in report.wrong_claims)


async def test_rejects_said_to_reduce_the_shortfall_are_rejected(analysis_run):
    """Live: "the 8 parts rejected, though this reduced the overall shortfall"."""
    total = analysis_run.analysis.rejected_quantity
    report = validate_answer(
        f"A12 was {analysis_run.analysis.pct_below_plan:g}% below plan. The secondary factor "
        f"was the {total} parts rejected, though this reduced the overall shortfall.",
        analysis_run,
    )
    assert any("do not reduce it" in claim for claim in report.wrong_claims)


async def test_the_correct_analysis_sentence_from_the_live_run_passes(analysis_run):
    """The run-1 S4 answer, word for word — the checks must not cry wolf on it."""
    a = analysis_run.analysis
    report = validate_answer(
        f"A12 production was {a.pct_below_plan:g}% below plan. The main reason was the "
        f"{a.downtime_hours:g} hours of downtime on CNC-02 due to a tool changer fault, "
        f"resulting in {a.parts_lost_to_downtime} parts not being produced. The secondary "
        f"factor was the {a.rejected_quantity} parts rejected, which is {a.reject_rate_pct:g}% "
        "of the processed parts.",
        analysis_run,
    )
    assert report.grounded, report.feedback()


async def test_over_production_reducing_the_shortfall_is_not_confused_with_rejects(analysis_run):
    a = analysis_run.analysis
    report = validate_answer(
        f"A12 was {a.pct_below_plan:g}% below plan. {a.rejected_quantity} parts were rejected, "
        "while CNC-03 produced 4 more than planned, which reduced the shortfall.",
        analysis_run,
    )
    assert not report.wrong_claims, report.feedback()


async def test_the_maintenance_answer_always_says_it_is_not_predictive(agent):
    """The brief's wording, supplied by the system when the model omits it — the
    live model dropped it in two of four maintenance answers."""
    run = await agent.ask("Which machine needs maintenance attention?")
    await write_and_validate(run, ScriptedExplainer("CNC-04 needs attention first."))
    assert run.answer_is_generated
    assert run.answer.endswith("not predictive maintenance.")


async def test_an_inverted_ranking_of_causes_is_rejected(analysis_run):
    """Live: "The main reason was the 8 parts rejected … The secondary factor was
    CNC-02's 2.1 hours of downtime" — the engine ranked downtime first."""
    a = analysis_run.analysis
    report = validate_answer(
        f"A12 was {a.pct_below_plan:g}% below plan. The main reason was the "
        f"{a.rejected_quantity} parts rejected. The secondary factor was CNC-02's "
        f"{a.downtime_hours:g} hours of downtime.",
        analysis_run,
    )
    assert any("main factor was" in claim for claim in report.wrong_claims)


async def test_a_correct_health_answer_with_a_negative_elsewhere_is_accepted(agent):
    """Live: a correct answer fell back twice because "do not exceed" counted as
    "cannot continue production"."""
    run = await agent.ask("Can CNC-03 continue production today?")
    report = validate_answer(
        "CNC-03 can continue production. Its readings do not exceed the limits, and no "
        "maintenance is active.",
        run,
    )
    assert report.grounded, report.feedback()


async def test_saying_the_machine_should_not_run_is_still_rejected(agent):
    run = await agent.ask("Can CNC-03 continue production today?")
    for sentence in (
        "CNC-03 should not continue production.",
        "CNC-03 is not safe to run today.",
        "Stop production on CNC-03.",
    ):
        report = validate_answer(sentence, run)
        assert not report.grounded, sentence


async def test_limiting_the_output_to_one_machines_share_is_rejected(bottleneck_run):
    """Live, after the first fix: "CNC-03 has 32 available hours, limiting the
    output to 548 units." — the pattern knew "limited to", not "limiting … to"."""
    finding_ = bottleneck_run.constraint.bottleneck
    report = validate_answer(
        f"CNC-03 has {finding_.effective_hours:g} available hours, limiting the output to "
        f"{finding_.parts_possible} units.",
        bottleneck_run,
    )
    assert any("not the total" in claim for claim in report.wrong_claims)


async def test_limiting_the_output_at_its_hours_is_not_a_total_claim(bottleneck_run):
    hours = bottleneck_run.constraint.bottleneck.effective_hours
    report = validate_answer(
        f"CNC-03 limits the output at {hours:g} available hours, because of its shorter shift "
        "pattern and scheduled maintenance.",
        bottleneck_run,
    )
    assert report.grounded, report.feedback()
