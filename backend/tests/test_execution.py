"""Day 5: running the plan (FR-4, FR-8).

These assert the behaviours the demo depends on — the documented tool sequence
actually executes, bindings carry values between steps, missing data stops the
run and names the field, and a tool that is not built yet is reported as such
rather than faked.
"""

from __future__ import annotations

import pytest

from app.agent.executor import PlanExecutor, _dig, _merge_sources
from app.agent.pipeline import AgentPipeline
from app.agent.schemas import ExecutedStep, Intent, RunStatus, StepStatus
from app.agent.understanding import UnderstandingPipeline
from app.schemas.envelope import SourceRef
from tests.conftest import requires_db

pytestmark = requires_db


@pytest.fixture
def understanding_pipeline(repo, ctx):
    return UnderstandingPipeline(repo=repo, clock=ctx.clock, llm=None, provider_name="none")


@pytest.fixture
def agent(repo, ctx):
    return AgentPipeline(repo=repo, clock=ctx.clock, llm=None, provider_name="none")


async def run(agent, question):
    return await agent.ask(question)


# ------------------------------------------------------------ the hero scenario


async def test_the_capacity_plan_executes_in_the_documented_order(agent):
    result = await run(agent, "How many A12 parts can we produce this week?")
    assert result.status is RunStatus.ANSWERED
    assert [s.tool for s in result.steps] == [
        "get_part_information",
        "get_available_machines",
        "get_maintenance_schedule",
        "get_material_inventory",
        "calculate_production_capacity",
    ]
    assert [s.step for s in result.steps] == [1, 2, 3, 4, 5]


async def test_the_hero_scenario_is_multi_step(agent):
    """Acceptance criterion 3: complex questions trigger multiple MES operations."""
    result = await run(agent, "How many A12 parts can we produce this week?")
    assert len(result.steps) >= 5
    assert result.tool_call_count >= 4


async def test_bindings_carry_values_between_steps(agent):
    """Step 2 needs the machine type step 1 returned; step 4 needs its material."""
    result = await run(agent, "How many A12 parts can we produce this week?")
    machines = next(s for s in result.steps if s.tool == "get_available_machines")
    assert machines.arguments["machine_type"] == "CNC_LATHE"
    assert machines.resolved_bindings["machine_type"]["from_step"] == 1
    assert (
        machines.resolved_bindings["machine_type"]["source_path"]
        == "data.part.required_machine_type"
    )

    inventory = next(s for s in result.steps if s.tool == "get_material_inventory")
    assert inventory.arguments["material_id"] == "STEEL-4140"


async def test_every_step_reports_what_it_found(agent):
    result = await run(agent, "How many A12 parts can we produce this week?")
    for step in result.steps:
        assert step.summary, f"step {step.step} has no summary"
    part_step = result.steps[0]
    assert "3.5 min/part" in part_step.summary and "STEEL-4140" in part_step.summary


async def test_data_used_is_merged_from_the_tools(agent):
    """Acceptance criterion 5 — assembled from tool output, not written by a model."""
    result = await run(agent, "How many A12 parts can we produce this week?")
    tables = {s.table for s in result.sources}
    assert {"parts", "machine_shift_calendar", "maintenance", "inventory"} <= tables
    assert len(result.sources) == len({s.table for s in result.sources}), "one entry per table"


# -------------------------------------------------- a tool that is not built yet


async def test_the_capacity_tool_is_reported_as_pending_not_failed(agent):
    result = await run(agent, "How many A12 parts can we produce this week?")
    calc = next(s for s in result.steps if s.tool == "calculate_production_capacity")
    assert calc.status is StepStatus.NOT_IMPLEMENTED
    assert "Day 6" in (calc.note or "")
    assert result.status is RunStatus.ANSWERED, "a pending step is not a failed run"
    assert result.headline is None, "no number is invented while the engine is missing"


# --------------------------------------------------------- missing data (FR-8)


async def test_a_missing_cycle_time_refuses_and_names_the_field(agent):
    """Scenario R3 — the refusal comes from a tool, not from a prompt."""
    result = await run(agent, "How many B20 parts can we produce tomorrow?")
    assert result.status is RunStatus.REFUSED_MISSING_DATA
    assert [m.field for m in result.missing_fields] == ["parts.cycle_time_min"]
    assert "parts.cycle_time_min" in result.answer
    assert result.headline is None


async def test_the_rest_of_the_plan_is_skipped_but_still_shown(agent):
    result = await run(agent, "How many B20 parts can we produce tomorrow?")
    assert result.steps[0].status is StepStatus.OK
    assert all(s.status is StepStatus.SKIPPED for s in result.steps[1:])
    assert len(result.steps) == 5, "the panel still shows the whole plan"


async def test_an_unrelated_missing_field_does_not_refuse(agent):
    """CNC-02's vibration sensor is offline; that must not block a health question."""
    result = await run(agent, "Which machine needs maintenance attention?")
    assert result.status is RunStatus.ANSWERED
    assert any(m.field == "machines.vibration_mm_s" for m in result.missing_fields)
    assert result.tool_call_count == 2


# ------------------------------------------------------- the other scenarios


async def test_machine_health_executes(agent):
    result = await run(agent, "Can CNC-03 continue production today?")
    assert result.status is RunStatus.ANSWERED
    assert result.intent is Intent.MACHINE_HEALTH
    assert "CNC-03" in result.steps[0].summary and "52.0" in result.steps[0].summary
    assert any(s.table == "rule_thresholds" for s in result.sources)


async def test_production_analysis_reads_the_incident(agent):
    result = await run(agent, "Why was A12 production lower yesterday?")
    assert result.status is RunStatus.ANSWERED
    history = result.steps[0].summary
    assert "planned 250" in history and "produced 215" in history
    assert "downtime 2.1 h" in history


async def test_the_downtime_cause_is_corroborated_by_maintenance(agent):
    """The S4 explanation must not rest on one table alone."""
    result = await run(agent, "Why was A12 production lower yesterday?")
    maintenance = next(s for s in result.steps if s.tool == "get_maintenance_schedule")
    assert "CNC-02" in maintenance.summary


async def test_bottleneck_executes_without_the_inventory_step(agent):
    result = await run(agent, "Which CNC machine is limiting A12 production?")
    assert [s.tool for s in result.steps] == [
        "get_part_information",
        "get_available_machines",
        "get_maintenance_schedule",
        "calculate_production_capacity",
    ]


# ------------------------------------------------- outcomes that run no tools


async def test_an_out_of_domain_request_executes_nothing(agent):
    """Acceptance criterion 7 — zero tool calls in the trace."""
    result = await run(agent, "Write me a story.")
    assert result.status is RunStatus.REJECTED_OUT_OF_DOMAIN
    assert result.steps == [] and result.sources == []
    assert result.answer.startswith("This AI assistant is restricted")


async def test_an_ambiguous_request_executes_nothing(agent):
    result = await run(agent, "How many A12?")
    assert result.status is RunStatus.CLARIFY
    assert result.steps == []
    assert result.clarification is not None
    assert "maximum production capacity" in result.answer.lower()


async def test_an_unknown_machine_is_answered_from_the_tool_result(agent):
    """Scenario R5 — the tool says it does not exist; the agent does not assert it."""
    result = await run(agent, "What is the status of CNC-09?")
    assert result.status is RunStatus.ANSWERED
    assert result.steps[0].not_found == ["CNC-09"]
    assert "does not exist" in result.steps[0].summary


# ---------------------------------------------------------------- properties


async def test_the_same_question_produces_the_same_run(agent):
    """What makes a live demo safe."""
    first = await run(agent, "How many A12 parts can we produce this week?")
    second = await run(agent, "How many A12 parts can we produce this week?")
    drop = {"run_id", "elapsed_ms", "steps", "understanding"}
    assert first.model_dump(exclude=drop) == second.model_dump(exclude=drop)
    assert [(s.tool, s.status, s.summary) for s in first.steps] == [
        (s.tool, s.status, s.summary) for s in second.steps
    ]


async def test_the_stream_and_the_collected_run_agree(agent):
    """One execution path, consumed two ways."""
    streamed = [event async for event in agent.stream("Can CNC-03 continue production today?")]
    kinds = [e.kind for e in streamed]
    assert kinds[0] == "accepted"
    assert kinds[1] == "understanding"
    assert kinds.count("tool_result") == 2
    assert kinds[-1] == "run"

    collected = await run(agent, "Can CNC-03 continue production today?")
    final = streamed[-1].run
    assert [s.tool for s in final.steps] == [s.tool for s in collected.steps]
    assert final.status is collected.status


# ------------------------------------------------------------------- units


def test_dig_follows_a_dotted_path():
    envelope = {"data": {"part": {"material_id": "STEEL-4140", "cycle_time_min": None}}}
    assert _dig(envelope, "data.part.material_id") == "STEEL-4140"
    assert _dig(envelope, "data.part.cycle_time_min") is None
    assert _dig(envelope, "data.part.missing") is None
    assert _dig(envelope, "nope.at.all") is None


def test_sources_merge_per_table_without_losing_fields():
    steps = [
        ExecutedStep(
            step=1,
            tool="a",
            title="a",
            status=StepStatus.OK,
            sources=[SourceRef(table="parts", fields=["cycle_time_min"], keys=["A12"], rows=1)],
        ),
        ExecutedStep(
            step=2,
            tool="b",
            title="b",
            status=StepStatus.OK,
            sources=[
                SourceRef(table="parts", fields=["material_id"], keys=["A12", "B20"], rows=2),
                SourceRef(table="machines", fields=["status"], keys=["CNC-01"], rows=1),
            ],
        ),
    ]
    merged = {s.table: s for s in _merge_sources(steps)}
    assert set(merged) == {"machines", "parts"}
    assert merged["parts"].fields == ["cycle_time_min", "material_id"]
    assert merged["parts"].keys == ["A12", "B20"]
    assert merged["parts"].rows == 3


async def test_a_step_is_skipped_when_its_binding_cannot_resolve(ctx, understanding_pipeline):
    """If step 1 has no material, step 4 cannot run — and says why."""
    understanding = await understanding_pipeline.understand(
        "How many A12 parts can we produce this week?"
    )
    # Break the plan the way a NULL in the MES would: point the binding at a
    # field that does not exist.
    inventory_step = next(p for p in understanding.plan if p.tool == "get_material_inventory")
    inventory_step.bindings[0].source_path = "data.part.no_such_field"

    result = await PlanExecutor(ctx).execute(understanding)
    step = next(s for s in result.steps if s.tool == "get_material_inventory")
    assert step.status is StepStatus.SKIPPED
    assert "did not provide it" in (step.note or "")
