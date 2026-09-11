"""The audit trail (`agent_run_log`).

Evidence for three acceptance criteria: that tools were called, that the answer
names its sources, and that an out-of-domain request touched nothing. Also the
demo's backup slide when a live run misbehaves.
"""

from __future__ import annotations

import uuid

from app.agent.pipeline import AgentPipeline
from app.agent.schemas import RunStatus
from app.agent.tracing import read_trace, recent_runs, record_run
from tests.conftest import requires_db

pytestmark = requires_db


async def _agent(repo, ctx) -> AgentPipeline:
    return AgentPipeline(repo=repo, clock=ctx.clock, llm=None, provider_name="none")


async def test_a_run_is_recorded_and_reads_back(app_pool, repo, ctx):
    agent = await _agent(repo, ctx)
    run = await agent.ask("How many A12 parts can we produce this week?")

    trace = await read_trace(run.run_id)
    assert trace is not None
    assert trace["question"] == "How many A12 parts can we produce this week?"
    assert trace["intent"] == "production_capacity"
    assert trace["status"] == RunStatus.ANSWERED.value
    assert trace["latency_ms"] >= 0


async def test_the_trace_keeps_the_plan_and_every_tool_call(app_pool, repo, ctx):
    agent = await _agent(repo, ctx)
    run = await agent.ask("How many A12 parts can we produce this week?")
    trace = await read_trace(run.run_id)

    assert [p["tool"] for p in trace["plan"]] == [
        "get_part_information",
        "get_available_machines",
        "get_maintenance_schedule",
        "get_material_inventory",
        "calculate_production_capacity",
    ]
    calls = trace["tool_calls"]
    assert len(calls) == 6, "five tool calls plus the engine step"
    assert trace["tool_call_count"] == 5, "the engine step is a calculation, not a tool call"
    assert calls[-1]["kind"] == "engine"
    # The arguments a reviewer needs to reproduce the run, including the ones
    # that were resolved from earlier steps.
    machines = next(c for c in calls if c["tool"] == "get_available_machines")
    assert machines["arguments"]["machine_type"] == "CNC_LATHE"
    assert machines["resolved_bindings"]["machine_type"]["from_step"] == 1
    assert machines["sources"]


async def test_the_trace_records_the_entities_that_were_resolved(app_pool, repo, ctx):
    agent = await _agent(repo, ctx)
    run = await agent.ask("What is the status of CNC-09?")
    trace = await read_trace(run.run_id)
    machines = trace["entities"]["machines"]
    assert machines[0]["id"] == "CNC-09" and machines[0]["exists"] is False


async def test_a_rejected_request_is_logged_with_no_tool_calls(app_pool, repo, ctx):
    """Acceptance criterion 7, evidenced rather than asserted."""
    agent = await _agent(repo, ctx)
    run = await agent.ask("Write me a story.")
    trace = await read_trace(run.run_id)
    assert trace["status"] == RunStatus.REJECTED_OUT_OF_DOMAIN.value
    assert trace["tool_calls"] == []
    assert trace["plan"] == []


async def test_a_refusal_is_logged_with_the_partial_plan(app_pool, repo, ctx):
    agent = await _agent(repo, ctx)
    run = await agent.ask("How many B20 parts can we produce tomorrow?")
    trace = await read_trace(run.run_id)
    assert trace["status"] == RunStatus.REFUSED_MISSING_DATA.value
    assert trace["tool_call_count"] == 1
    missing = trace["tool_calls"][0]["missing_fields"]
    assert missing[0]["field"] == "parts.cycle_time_min"


async def test_recent_runs_are_listed_newest_first(app_pool, repo, ctx):
    agent = await _agent(repo, ctx)
    await agent.ask("Can CNC-03 continue production today?")
    runs = await recent_runs(limit=5)
    assert runs
    assert runs[0]["question"] == "Can CNC-03 continue production today?"
    assert {"run_id", "asked_at", "intent", "status", "latency_ms"} <= set(runs[0])


async def test_an_unknown_run_id_has_no_trace(app_pool):
    assert await read_trace(str(uuid.uuid4())) is None


async def test_recording_the_same_run_twice_is_harmless(app_pool, repo, ctx):
    agent = await _agent(repo, ctx)
    run = await agent.ask("Can CNC-03 continue production today?")
    assert await record_run(run) is True  # ON CONFLICT DO NOTHING


async def test_a_run_survives_an_unavailable_audit_log(repo, ctx):
    """The answer must reach the user even if it cannot be recorded."""
    import app.db as db_module

    saved, db_module._app_pool = db_module._app_pool, None
    try:
        agent = await _agent(repo, ctx)
        run = await agent.ask("Can CNC-03 continue production today?")
        assert run.status is RunStatus.ANSWERED
        assert any("not written to the audit log" in n for n in run.notes)
    finally:
        db_module._app_pool = saved
