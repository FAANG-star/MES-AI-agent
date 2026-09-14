"""Run the plan (FR-4).

Understanding produces an ordered plan with declared argument bindings. This runs it:
each step through the controlled tool layer, each binding resolved from an
earlier step's result, each envelope folded into one structured `AgentRun`.

Three properties are worth stating, because they are what the execution model
buys:

**The plan is the state machine.** It arrives already ordered, already validated
against the registry, with dependencies declared rather than discovered. So
execution is a bounded walk over a fixed list — it cannot loop, cannot call a
tool that was not planned, and cannot vary between two runs of the same question.
The brief allows "LangGraph or a simple custom tool-calling agent"; with the graph
already static and inspectable, a graph library would add a dependency and an
indirection without adding a guarantee.

**Missing data stops the run, and the plan says which data.** Each step declares
the fields it must come back with. If a tool reports one of them in
`missing_fields`, the run refuses and names the field and the tool that reported
it — FR-8 as data, not as a special case buried in code.

**A tool that is not built yet is not a failure.** A tool registered as declared
but not implemented records `not_implemented` with what it is planned for, the run
continues, and the answer says plainly that the number is not available. An honest
gap beats a fabricated total.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from app.agent.derive import derive
from app.agent.schemas import (
    AgentRun,
    ExecutedStep,
    RunStatus,
    StepStatus,
    Understanding,
    UnderstandingStatus,
)
from app.schemas.envelope import MissingField, SourceRef
from app.timewindow import WindowError
from app.tools.registry import (
    ToolContext,
    ToolError,
    ToolNotImplementedError,
    ToolParameterError,
    registry,
)

log = logging.getLogger(__name__)


class PlanExecutor:
    def __init__(self, ctx: ToolContext) -> None:
        self._ctx = ctx

    async def execute(self, understanding: Understanding, *, run_id: str | None = None) -> AgentRun:
        """Run the plan to completion and return the finished run."""
        run: AgentRun | None = None
        async for kind, item in self.execute_stream(understanding, run_id=run_id):
            if kind == "run":
                run = item
        assert run is not None  # execute_stream always ends with a run
        return run

    async def execute_stream(
        self, understanding: Understanding, *, run_id: str | None = None
    ) -> AsyncIterator[tuple[str, Any]]:
        """Yield ("step", ExecutedStep) as each completes, then ("run", AgentRun).

        One execution path, consumed two ways: `execute()` collects it, the API's
        SSE endpoint forwards it. A second implementation for streaming would be
        a second thing to keep correct.
        """
        started = time.perf_counter()
        run = AgentRun(
            run_id=run_id or str(uuid.uuid4()),
            status=RunStatus.ANSWERED,
            question=understanding.question,
            rewritten_question=understanding.rewritten_question,
            intent=understanding.intent,
            metric=understanding.metric,
            window=understanding.window,
            understanding=understanding,
            notes=list(understanding.notes),
        )

        # Outcomes the understanding layer already settled: no tool may run.
        if understanding.status is UnderstandingStatus.REJECTED_OUT_OF_DOMAIN:
            run.status = RunStatus.REJECTED_OUT_OF_DOMAIN
            run.rejection = understanding.rejection
            run.answer = understanding.rejection or ""
            yield "run", self._finish(run, started)
            return

        if understanding.status is UnderstandingStatus.CLARIFY:
            run.status = RunStatus.CLARIFY
            run.clarification = understanding.clarification
            run.answer = understanding.clarification.question if understanding.clarification else ""
            yield "run", self._finish(run, started)
            return

        results: dict[int, dict] = {}  # step number → the envelope it produced
        typed: dict[int, object] = {}  # step number → the typed result, for the engine

        for planned in understanding.plan:
            step = await self._run_step(planned, results)
            run.steps.append(step)
            yield "step", step

            if step.status is StepStatus.OK and step.detail is not None:
                results[planned.step] = step.detail
                if step._typed is not None:
                    typed[planned.step] = step._typed

            fatal = self._fatal_missing(planned.requires, step.missing_fields)
            if fatal:
                run.missing_fields.extend(fatal)
                for skipped in self._mark_remaining_skipped(
                    run,
                    understanding,
                    after=planned.step,
                    why="an earlier step reported missing data",
                ):
                    yield "step", skipped
                run.status = RunStatus.REFUSED_MISSING_DATA
                break

            if step.status is StepStatus.FAILED:
                for skipped in self._mark_remaining_skipped(
                    run, understanding, after=planned.step, why="an earlier step failed"
                ):
                    yield "step", skipped
                run.status = RunStatus.ERROR
                break

        # Step 6: the deterministic engine turns the collected facts into the
        # findings the question asked for. Recorded as its own step so a
        # reviewer can see exactly where each number entered the answer.
        if run.status is RunStatus.ANSWERED:
            derived = derive(run, typed)
            if derived is not None:
                run.steps.append(derived)
                yield "step", derived

        run.sources = _merge_sources(run.steps)
        for step in run.steps:
            for missing in step.missing_fields:
                if missing not in run.missing_fields:
                    run.missing_fields.append(missing)

        run.answer = _compose_answer(run)
        yield "run", self._finish(run, started)

    # ------------------------------------------------------------------ steps

    async def _run_step(self, planned, results: dict[int, dict]) -> ExecutedStep:
        started = time.perf_counter()
        step = ExecutedStep(
            step=planned.step,
            tool=planned.tool,
            title=planned.title,
            status=StepStatus.OK,
            arguments=dict(planned.arguments),
        )

        # Resolve what earlier steps were supposed to provide.
        for binding in planned.bindings:
            source = results.get(binding.from_step)
            value = _dig(source, binding.source_path) if source else None
            if value is None:
                step.status = StepStatus.SKIPPED
                step.note = (
                    f"{binding.parameter} was to come from step {binding.from_step} "
                    f"({binding.source_path}), which did not provide it."
                )
                step.summary = f"Skipped — {binding.parameter} was not available."
                step.elapsed_ms = int((time.perf_counter() - started) * 1000)
                return step
            step.arguments[binding.parameter] = value
            step.resolved_bindings[binding.parameter] = {
                "value": value,
                "from_step": binding.from_step,
                "source_path": binding.source_path,
            }

        try:
            result = await registry.invoke(planned.tool, step.arguments, self._ctx)
        except ToolNotImplementedError as exc:
            step.status = StepStatus.NOT_IMPLEMENTED
            step.note = f"{exc.name} arrives on {exc.planned_for}."
            step.summary = f"Not available yet — {exc.planned_for}."
            step.elapsed_ms = int((time.perf_counter() - started) * 1000)
            return step
        except (ToolParameterError, WindowError, ToolError) as exc:
            log.warning("Step %s (%s) failed: %s", planned.step, planned.tool, exc)
            step.status = StepStatus.FAILED
            step.note = str(exc)
            step.summary = "Failed."
            step.elapsed_ms = int((time.perf_counter() - started) * 1000)
            return step

        envelope = result.model_dump(mode="json")
        step.detail = envelope
        step._typed = result
        step.sources = result.sources
        step.missing_fields = result.missing_fields
        step.not_found = result.not_found
        step.warnings = result.warnings
        step.summary = _summarise(planned.tool, result)
        step.elapsed_ms = result.elapsed_ms or int((time.perf_counter() - started) * 1000)
        return step

    @staticmethod
    def _fatal_missing(requires: list[str], missing: list[MissingField]) -> list[MissingField]:
        """Only the fields this step declared as required stop the run.

        A NULL vibration reading must not refuse a capacity question; a NULL
        cycle time must refuse it. The difference lives in the plan.
        """
        required = set(requires)
        return [m for m in missing if m.field in required]

    @staticmethod
    def _mark_remaining_skipped(
        run: AgentRun, understanding: Understanding, *, after: int, why: str
    ) -> list[ExecutedStep]:
        """Record the steps that will not run, so the panel shows the whole plan."""
        skipped: list[ExecutedStep] = []
        for planned in understanding.plan:
            if planned.step > after:
                step = ExecutedStep(
                    step=planned.step,
                    tool=planned.tool,
                    title=planned.title,
                    status=StepStatus.SKIPPED,
                    arguments=dict(planned.arguments),
                    summary=f"Skipped — {why}.",
                    note=why,
                )
                run.steps.append(step)
                skipped.append(step)
        return skipped

    @staticmethod
    def _finish(run: AgentRun, started: float) -> AgentRun:
        run.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return run


# ------------------------------------------------------------------- helpers


def _dig(payload: Any, path: str) -> Any:
    """Follow a dotted path into a tool envelope, e.g. 'data.part.material_id'."""
    current = payload
    for key in path.split("."):
        if isinstance(current, dict):
            current = current.get(key)
        else:
            current = getattr(current, key, None)
        if current is None:
            return None
    return current


def _merge_sources(steps: list[ExecutedStep]) -> list[SourceRef]:
    """One entry per table, with the fields and keys every step touched.

    This is the "Data Used" panel. It is assembled from what the tools reported,
    never written by the model.
    """
    merged: dict[str, SourceRef] = {}
    for step in steps:
        for source in step.sources:
            existing = merged.get(source.table)
            if existing is None:
                merged[source.table] = SourceRef(
                    table=source.table,
                    fields=list(source.fields),
                    keys=list(source.keys),
                    rows=source.rows,
                )
                continue
            existing.fields = _ordered_union(existing.fields, source.fields)
            existing.keys = _ordered_union(existing.keys, source.keys)
            existing.rows += source.rows
    return [merged[table] for table in sorted(merged)]


def _ordered_union(first: list[str], second: list[str]) -> list[str]:
    seen = set(first)
    return first + [item for item in second if not (item in seen or seen.add(item))]


def _summarise(tool: str, result) -> str:
    """One readable line per step, built from the data — never from the model."""
    data = result.data
    if result.not_found:
        return f"{', '.join(result.not_found)} does not exist in the MES."
    if data is None:
        return "No data returned."

    match tool:
        case "get_part_information":
            part = getattr(data, "part", None)
            if part is None:
                return "Part not found."
            cycle = (
                f"{part.cycle_time_min} min/part" if part.cycle_time_min else "cycle time unknown"
            )
            return (
                f"{part.part_id}: {cycle}, {part.required_machine_type}, "
                f"material {part.material_id}."
            )
        case "get_available_machines":
            eligible = getattr(data, "eligible_machine_ids", [])
            hours = getattr(data, "total_effective_hours", 0)
            return f"{len(eligible)} eligible machine(s), {hours} effective hours in the window."
        case "get_maintenance_schedule":
            hours = getattr(data, "hours_by_machine", {}) or {}
            events = getattr(data, "events", []) or []
            if hours:
                parts = ", ".join(f"{m} {h} h" for m, h in sorted(hours.items()))
                return f"Maintenance in the window: {parts}."
            if events:
                # Completed work carries no scheduled hours but is exactly what
                # a past-shortfall question needs: the unplanned stop that
                # explains it. Saying "none scheduled" would hide the cause.
                machines = ", ".join(sorted({e.machine_id for e in events}))
                return f"{len(events)} completed maintenance record(s) in the window: {machines}."
            return "No maintenance in the window."
        case "get_material_inventory":
            items = getattr(data, "items", [])
            if not items:
                return "No material record."
            item = items[0]
            if item.available_quantity is None:
                return f"{item.material_id}: stock unknown."
            return f"{item.material_id}: {item.available_quantity:g} {item.unit} on hand."
        case "get_machine_status":
            machines = getattr(data, "machines", [])
            if len(machines) == 1:
                m = machines[0]
                temp = f"{m.temperature_c} °C" if m.temperature_c is not None else "temp unknown"
                vib = (
                    f"{m.vibration_mm_s} mm/s"
                    if m.vibration_mm_s is not None
                    else "vibration unknown"
                )
                return f"{m.machine_id}: {m.status}, {temp}, {vib}."
            return f"{len(machines)} machines read, with the factory's condition thresholds."
        case "get_production_history":
            totals = getattr(data, "totals", None)
            if totals is None or totals.planned_quantity == 0:
                return "No production recorded in the window."
            return (
                f"planned {totals.planned_quantity}, produced {totals.produced_quantity}, "
                f"rejected {totals.rejected_quantity}, downtime {totals.downtime_hours} h."
            )
        case "calculate_production_capacity":
            capacity = getattr(data, "capacity", None)
            constraint = getattr(data, "constraint", None)
            if capacity is None:
                return "Capacity could not be calculated."
            line = (
                f"{capacity.final_capacity} units possible "
                f"({capacity.binding_constraint}-constrained)"
            )
            if constraint is not None and constraint.bottleneck is not None:
                line += (
                    f"; {constraint.bottleneck.machine_id} limits it at "
                    f"{constraint.bottleneck.effective_hours:g} h"
                )
            return line + "."
        case "get_production_orders":
            totals = getattr(data, "totals", None)
            if totals is None or totals.orders == 0:
                return "No matching production orders."
            return (
                f"{totals.orders} order(s): planned {totals.planned_quantity}, "
                f"completed {totals.completed_quantity}, remaining {totals.remaining_quantity}."
            )
    return "Data retrieved."


def _compose_answer(run: AgentRun) -> str:
    """A deterministic account of what was found.

    The explainer puts the model's wording on top of this, validated against the
    tool results; this text is what a failed validation falls back to. It is
    assembled from the step summaries, so it is always something a tool returned.
    """
    if run.status is RunStatus.REFUSED_MISSING_DATA:
        missing = run.missing_fields[0]
        return (
            f"I cannot answer this because {missing.field} is not available for "
            f"{missing.entity}. {missing.reason}"
        )

    if run.status is RunStatus.ERROR:
        failed = next((s for s in run.steps if s.status is StepStatus.FAILED), None)
        return f"The request could not be completed: {failed.note if failed else 'unknown error'}"

    # Lead with what the engine concluded, then the evidence behind it. This is
    # assembled deterministically, so every line is something a tool returned or
    # a pure function computed.
    lines: list[str] = []
    engine_step = next((s for s in run.steps if s.kind == "engine"), None)
    if engine_step is not None and engine_step.summary:
        lines.append(engine_step.summary)

    if run.capacity is not None:
        lines.append("Working: " + " · ".join(run.capacity.formula[-3:]))
    if run.analysis is not None and run.analysis.factors:
        lines.extend(f"- {factor.detail}" for factor in run.analysis.factors)
    if run.health and len(run.health) == 1:
        lines.extend(f"- {check.verdict}" for check in run.health[0].checks)

    if not lines:
        lines = [
            f"{s.title}: {s.summary}"
            for s in run.steps
            if s.status is StepStatus.OK and s.kind == "tool"
        ]

    pending = [s for s in run.steps if s.status is StepStatus.NOT_IMPLEMENTED]
    if pending:
        lines.append("Not yet available: " + "; ".join(f"{s.title} ({s.note})" for s in pending))
    if not lines:
        return "No factory data was retrieved for this question."
    return "\n".join(lines)


def unknown_entity_note(run: AgentRun) -> str | None:
    """Scenario R5, sourced from a tool result rather than asserted."""
    for step in run.steps:
        if step.not_found and step.detail:
            known = (step.detail.get("data") or {}).get("known_machine_ids") or (
                step.detail.get("data") or {}
            ).get("known_part_ids")
            if known:
                missing = ", ".join(step.not_found)
                return f"{missing} does not exist in the MES. Known: {', '.join(known)}."
    return None
