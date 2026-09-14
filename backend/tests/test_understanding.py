"""The understanding pipeline end to end, against the seeded factory.

The plans asserted here are the tool sequences docs/04-demo-scenarios.md fixes
for each scenario. If a change breaks one of these, it breaks the demo.
"""

from __future__ import annotations

import pytest

from app.agent.schemas import Intent, UnderstandingStatus
from app.agent.understanding import UnderstandingPipeline
from app.config import get_settings
from tests.conftest import requires_db

pytestmark = requires_db


@pytest.fixture
def pipeline(repo, ctx):
    return UnderstandingPipeline(repo=repo, clock=ctx.clock, llm=None, provider_name="none")


# --------------------------------------------------------- the five scenarios


async def test_s1_capacity_plans_the_documented_tool_sequence(pipeline):
    u = await pipeline.understand("How many A12 parts can we produce this week?")
    assert u.status is UnderstandingStatus.UNDERSTOOD
    assert u.intent is Intent.PRODUCTION_CAPACITY
    assert [s.tool for s in u.plan] == [
        "get_part_information",
        "get_available_machines",
        "get_maintenance_schedule",
        "get_material_inventory",
        "calculate_production_capacity",
    ]
    assert len(u.plan) >= 5, "acceptance criterion 3: the hero scenario is multi-step"


async def test_s2_machine_health_plan(pipeline):
    u = await pipeline.understand("Can CNC-03 continue production today?")
    assert u.intent is Intent.MACHINE_HEALTH
    assert [s.tool for s in u.plan] == ["get_machine_status", "get_maintenance_schedule"]
    assert u.plan[0].arguments["machine_id"] == "CNC-03"
    assert u.window.start == u.window.end == pipeline._clock.today()


async def test_s3_bottleneck_plan(pipeline):
    u = await pipeline.understand("Which CNC machine is limiting A12 production?")
    assert u.intent is Intent.BOTTLENECK
    assert [s.tool for s in u.plan] == [
        "get_part_information",
        "get_available_machines",
        "get_maintenance_schedule",
        "calculate_production_capacity",
    ]


async def test_s4_analysis_plan(pipeline):
    u = await pipeline.understand("Why was A12 production lower yesterday?")
    assert u.intent is Intent.PRODUCTION_ANALYSIS
    assert [s.tool for s in u.plan] == [
        "get_part_information",
        "get_production_history",
        "get_production_orders",
        "get_maintenance_schedule",
    ]
    assert u.plan[3].arguments["include_completed"] is True
    # The cycle time is what converts downtime hours into parts, so the causes
    # can be ranked against each other rather than merely listed.
    assert u.plan[0].requires == [], "a missing cycle time must not refuse an analysis"


async def test_s5_maintenance_plan(pipeline):
    u = await pipeline.understand("Which machine needs maintenance attention?")
    assert u.intent is Intent.MAINTENANCE_ATTENTION
    assert [s.tool for s in u.plan] == ["get_machine_status", "get_maintenance_schedule"]
    assert u.plan[0].arguments == {}, "all machines, not one"


# ----------------------------------------------------------- reliability cases


async def test_r1_an_elliptical_question_behaves_like_the_full_one(pipeline):
    short = await pipeline.understand("How many A12 this week?")
    full = await pipeline.understand("How many A12 parts can we produce this week?")
    assert short.status is UnderstandingStatus.UNDERSTOOD
    assert short.intent is full.intent
    assert [s.tool for s in short.plan] == [s.tool for s in full.plan]
    assert short.rewritten_question and short.rewritten_question != short.question


async def test_r2_an_ambiguous_question_asks_one_question_and_plans_nothing(pipeline):
    u = await pipeline.understand("How many A12?")
    assert u.status is UnderstandingStatus.CLARIFY
    assert u.plan == []
    assert u.clarification is not None
    assert "maximum production capacity" in u.clarification.question.lower()
    assert len(u.clarification.options) >= 3


async def test_r3_a_part_without_a_cycle_time_still_plans(pipeline):
    """The refusal is data-driven: the tool reports the missing field at execution."""
    u = await pipeline.understand("How many B20 parts can we produce tomorrow?")
    assert u.status is UnderstandingStatus.UNDERSTOOD
    assert u.entities.parts[0].id == "B20" and u.entities.parts[0].exists
    assert u.plan[0].tool == "get_part_information"


async def test_r4_out_of_domain_is_rejected_with_no_plan(pipeline):
    for question in ("Write me a story.", "Write a poem about summer."):
        u = await pipeline.understand(question)
        assert u.status is UnderstandingStatus.REJECTED_OUT_OF_DOMAIN
        assert u.plan == [] and u.rejection
        assert u.entities.known_machine_ids == [], (
            "no factory data may be read for a rejected request"
        )


async def test_r5_an_unknown_machine_is_flagged_against_the_real_mes(pipeline):
    u = await pipeline.understand("What is the status of CNC-09?")
    assert u.entities.machines[0].id == "CNC-09"
    assert u.entities.machines[0].exists is False
    assert u.entities.has_unknown
    assert u.entities.known_machine_ids == ["CNC-01", "CNC-02", "CNC-03", "CNC-04", "CNC-05"]
    assert any("does not exist" in note for note in u.notes)


async def test_a_known_machine_resolves_cleanly(pipeline):
    u = await pipeline.understand("What is the status of CNC-03?")
    assert u.entities.machines[0].exists and not u.entities.has_unknown


async def test_informal_machine_ids_are_normalised(pipeline):
    u = await pipeline.understand("Can cnc 3 continue production today?")
    assert u.entities.machines[0].id == "CNC-03"
    assert u.entities.machines[0].exists


async def test_a_part_question_without_a_part_asks_which_one(pipeline):
    u = await pipeline.understand("What is the production capacity this week?")
    assert u.status is UnderstandingStatus.CLARIFY
    assert "A12" in u.clarification.options


# ------------------------------------------------------------------ mechanics


async def test_the_plan_declares_arguments_that_come_from_earlier_steps(pipeline):
    u = await pipeline.understand("How many A12 parts can we produce this week?")
    machines_step = next(s for s in u.plan if s.tool == "get_available_machines")
    binding = machines_step.bindings[0]
    assert binding.parameter == "machine_type"
    assert binding.from_step == 1
    assert binding.source_path == "data.part.required_machine_type"


async def test_every_planned_tool_exists_in_the_registry(pipeline):
    from app.tools.registry import registry

    for question in (
        "How many A12 parts can we produce this week?",
        "Why was A12 production lower yesterday?",
        "Which machine needs maintenance attention?",
    ):
        u = await pipeline.understand(question)
        for step in u.plan:
            assert step.tool in registry.names()


async def test_every_step_carries_a_title_and_a_reason_for_the_ui(pipeline):
    u = await pipeline.understand("How many A12 parts can we produce this week?")
    assert all(s.title and s.reason for s in u.plan)
    assert [s.step for s in u.plan] == list(range(1, len(u.plan) + 1))


async def test_windows_are_resolved_to_factory_local_dates(pipeline):
    u = await pipeline.understand("How many A12 parts can we produce this week?")
    assert u.window.timezone == get_settings().factory_timezone
    assert u.window.start == pipeline._clock.today(), "elapsed days are excluded"


async def test_understanding_is_reproducible(pipeline):
    """Same question, same reading — what makes a live demo safe."""
    first = await pipeline.understand("How many A12 parts can we produce this week?")
    second = await pipeline.understand("How many A12 parts can we produce this week?")
    assert first.model_dump(exclude={"elapsed_ms"}) == second.model_dump(exclude={"elapsed_ms"})


async def test_a_degraded_run_is_labelled_as_such(pipeline):
    u = await pipeline.understand("How many A12 parts can we produce this week?")
    assert u.understood_by == "rules" and u.degraded is True and u.provider == "none"


async def test_an_unrecognised_request_is_offered_what_the_agent_can_do(pipeline):
    """A clarification must not guess the subject it is clarifying.

    "SELECT * FROM machines;" carries a factory word, so it passes the guard,
    and extraction cannot tell what it wants — the agent then asked whether the
    manager meant maximum, planned or actual *production*, a reading nothing in
    the request supports. With no intent, the honest question lists what the
    assistant can answer.
    """
    u = await pipeline.understand("SELECT * FROM machines;")
    assert u.status is UnderstandingStatus.CLARIFY
    assert u.plan == []
    assert u.intent is Intent.UNKNOWN
    assert "could not tell" in u.clarification.question.lower()
    assert any("maintenance attention" in option for option in u.clarification.options)
    assert not any("Planned production quantity" == option for option in u.clarification.options)


async def test_a_tool_the_model_adds_is_recorded_but_not_run(repo, ctx):
    """Live scenario matrix: the model added get_production_history to every
    bottleneck question. Nothing in the answer reads it; running it only padded
    Data Used and widened the set of numbers the validator would accept."""
    from app.agent.schemas import ExtractedIntent
    from tests.test_extractor import ScriptedLLM

    question = "Which CNC machine is limiting A12 production?"
    scripted = ScriptedLLM(
        ExtractedIntent(
            rewritten_question="Identify which CNC machine limits A12 production this week.",
            intent=Intent.BOTTLENECK,
            part_ids=["A12"],
            time_window="this_week",
            required_tools=["get_part_information", "get_production_history"],
        )
    )
    u = await UnderstandingPipeline(
        repo=repo, clock=ctx.clock, llm=scripted, provider_name="scripted"
    ).understand(question)

    assert "get_production_history" not in [step.tool for step in u.plan]
    assert any("get_production_history" in note and "not run" in note for note in u.notes)
