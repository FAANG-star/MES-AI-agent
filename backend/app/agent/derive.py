"""Step 6: turn tool results into findings, deterministically.

The tool layer reports facts — 3.1 mm/s, 50 available hours, 215 produced
against 250 planned. This is where those become the conclusions a factory
manager asked for: a capacity number, a named bottleneck, a fit-to-run verdict,
a ranked attention list, a quantified shortfall.

Every one of them comes from `app/engine/`, which is pure Python with unit
tests. Nothing here calls a model, and nothing here invents a value: this module
only chooses **which** engine function the intent calls for and packages what it
returns.

That is the split acceptance criterion 4 turns on, and it is visible in the
trace — the derivation is recorded as its own step with `kind="engine"`, so a
reviewer can see exactly where a number entered the answer and which function
produced it.
"""

from __future__ import annotations

import logging
import time

from app.agent.schemas import (
    AgentRun,
    Bottleneck,
    ExecutedStep,
    Headline,
    Intent,
    StepStatus,
)
from app.engine import analyse_production, evaluate_machine, rank_attention
from app.engine.analysis import analyse_production as _analyse  # noqa: F401  (re-export clarity)
from app.schemas.envelope import ToolResult

log = logging.getLogger(__name__)

# Which engine step each intent gets, and what to call it in the panel.
DERIVATION_TITLES: dict[Intent, str] = {
    Intent.PRODUCTION_CAPACITY: "Rank the constraint and confirm the limit",
    Intent.BOTTLENECK: "Rank machines by available hours",
    Intent.MACHINE_HEALTH: "Apply the factory's condition rules",
    Intent.MACHINE_STATUS: "Apply the factory's condition rules",
    Intent.MAINTENANCE_ATTENTION: "Rank machines needing attention",
    Intent.PRODUCTION_ANALYSIS: "Compare plan with actual and rank the causes",
}


def _find(typed: dict[int, ToolResult], tool: str) -> ToolResult | None:
    for result in typed.values():
        if result.tool == tool and result.ok and result.data is not None:
            return result
    return None


def derive(run: AgentRun, typed: dict[int, ToolResult]) -> ExecutedStep | None:
    """Apply the engine for this run's intent. Returns the step to append, if any."""
    started = time.perf_counter()
    title = DERIVATION_TITLES.get(run.intent)
    if title is None:
        return None

    summary = ""
    match run.intent:
        case Intent.PRODUCTION_CAPACITY | Intent.BOTTLENECK:
            summary = _derive_capacity(run, typed)
        case Intent.MACHINE_HEALTH | Intent.MACHINE_STATUS:
            summary = _derive_health(run, typed, single=True)
        case Intent.MAINTENANCE_ATTENTION:
            summary = _derive_health(run, typed, single=False)
        case Intent.PRODUCTION_ANALYSIS:
            summary = _derive_analysis(run, typed)

    if not summary:
        return None

    return ExecutedStep(
        step=len(run.steps) + 1,
        tool="calculation_engine",
        kind="engine",
        title=title,
        status=StepStatus.OK,
        summary=summary,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        note="Deterministic Python; no language model is involved in this step.",
    )


def _derive_capacity(run: AgentRun, typed: dict[int, ToolResult]) -> str:
    result = _find(typed, "calculate_production_capacity")
    if result is None or result.data.capacity is None:
        return ""

    capacity = result.data.capacity
    constraint = result.data.constraint
    run.capacity = capacity
    run.constraint = constraint

    part = capacity.part_id
    run.headline = Headline(
        label=f"Estimated {part} capacity",
        value=capacity.final_capacity,
        unit="units",
    )

    if constraint is not None and constraint.kind == "machine" and constraint.bottleneck:
        found = constraint.bottleneck
        run.bottleneck = Bottleneck(
            machine_id=found.machine_id,
            reason=f"{found.effective_hours:g} effective hours — {found.cause}",
        )
        return (
            f"{capacity.final_capacity} units, {capacity.binding_constraint}-constrained; "
            f"{found.machine_id} is the bottleneck at {found.effective_hours:g} h."
        )
    if constraint is not None and constraint.kind == "material":
        return (
            f"{capacity.final_capacity} units, material-constrained by "
            f"{capacity.material_id}; no single machine is the limit."
        )
    return (
        f"{capacity.final_capacity} units; {constraint.explanation if constraint else ''}".strip()
    )


def _derive_health(run: AgentRun, typed: dict[int, ToolResult], *, single: bool) -> str:
    status_result = _find(typed, "get_machine_status")
    if status_result is None:
        return ""

    machines = status_result.data.machines
    thresholds = status_result.data.thresholds
    if not machines:
        return ""

    under_maintenance: set[str] = set()
    maintenance_result = _find(typed, "get_maintenance_schedule")
    if maintenance_result is not None:
        under_maintenance = set(maintenance_result.data.machines_under_maintenance_today)

    healths = [
        evaluate_machine(
            machine, thresholds, under_maintenance_today=machine.machine_id in under_maintenance
        )
        for machine in machines
    ]

    if single and len(healths) == 1:
        health = healths[0]
        run.health = healths
        run.headline = Headline(
            label=health.machine_id,
            text="Can continue production" if health.can_produce else "Cannot continue production",
        )
        return health.reason

    ranked = rank_attention(healths)
    run.health = ranked
    top = ranked[0]
    if top.breaches == 0:
        run.headline = Headline(label="Maintenance attention", text="No machine breaches a limit")
        unknown = [h.machine_id for h in ranked if not h.fully_assessable]
        note = f" {', '.join(unknown)} could not be fully assessed." if unknown else ""
        return f"No machine breaches a condition threshold.{note}"

    run.headline = Headline(label="Needs attention first", text=top.machine_id)
    return (
        f"{top.machine_id} needs attention first — {top.attention_note} "
        f"This is a rule-based check against the factory's thresholds, not predictive maintenance."
    )


def _derive_analysis(run: AgentRun, typed: dict[int, ToolResult]) -> str:
    history = _find(typed, "get_production_history")
    if history is None or not history.data.rows:
        return ""

    part_ids = {row.part_id for row in history.data.rows}
    part_id = next(iter(part_ids)) if len(part_ids) == 1 else None

    # The cycle time converts downtime hours into parts, which is what lets the
    # factors be ranked against each other. It comes from a tool result when the
    # plan fetched one; without it the downtime factor stays unquantified rather
    # than being guessed at.
    cycle_time = None
    part_result = _find(typed, "get_part_information")
    if part_result is not None and part_result.data.part is not None:
        cycle_time = part_result.data.part.cycle_time_min

    analysis = analyse_production(history.data.rows, part_id=part_id, cycle_time_min=cycle_time)
    run.analysis = analysis
    if analysis.pct_below_plan is not None and analysis.shortfall > 0:
        run.headline = Headline(
            label=f"{part_id or 'Production'} below plan",
            value=analysis.pct_below_plan,
            unit="%",
        )
    return analysis.summary
