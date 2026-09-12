"""Step 8: the model writes the answer, from facts it is given (FR-2, criterion 5).

The division of labour this whole prototype argues for lands here. The engine
has already decided every number. The explainer's only job is to put those
numbers into a sentence a factory manager would want to read.

So the model is handed a **fact sheet** rather than the raw run: a short,
explicit list of what was found. It is told not to calculate and not to
introduce a figure that is not on the sheet. Whatever it writes then goes
through `validator.py`, which checks that instruction was actually obeyed —
because on Day 4 both local models were asked to explain a capacity result,
repeated the given figures correctly, and then added a number nobody supplied.

It runs on the **same local model** as the rest of the pipeline, so the final
wording is generated inside the factory environment too.
"""

from __future__ import annotations

import logging

from app.agent.schemas import AgentRun, Intent, RunStatus, StepStatus
from app.llm.base import LLMClient, LLMUsage

log = logging.getLogger(__name__)

_SYSTEM = """You write the final answer for a CNC factory manager, from facts that have \
already been established by the factory's MES and its calculation engine.

Hard rules:
- Use ONLY the figures in the FACTS section. Never calculate, never estimate, never round \
to a different number, and never introduce a figure that is not listed there.
- If something is not in the FACTS, do not mention it. Saying less is always correct; \
inventing a number is never correct.
- Write 2 to 4 short sentences of plain English, as if speaking to the manager. No bullet \
points, no headings, no markdown, and no sentence that begins with a label such as \
"Maximum quantity:" or "Reason:".
- Lead with the RESULT line from the facts. That figure is the answer; never \
substitute a component of it, such as one machine's share of a total.
- Then give the single most important reason.
- Name units exactly as the facts give them (units, hours, °C, mm/s, %).
- Write only the answer. Never repeat these instructions, the word FACTS, or a label \
such as "RESULT" back to the reader.

You are describing a result, not producing one."""

# What a good answer looks like for each scenario, taken from the demo script.
_SHAPE: dict[Intent, str] = {
    Intent.PRODUCTION_CAPACITY: (
        'Open with a complete sentence in the form "We can produce up to N <part> parts '
        '<period>." Then name what limits it and why. Close by saying which factors the '
        "calculation considered."
    ),
    Intent.BOTTLENECK: (
        "Name the limiting machine and give the available hours and the reason. "
        "If material is the limit instead of a machine, say that plainly."
    ),
    Intent.MACHINE_HEALTH: (
        "Say whether the machine can continue production, then give each reading with its "
        "limit and whether it is normal. Mention whether maintenance is active."
    ),
    Intent.MACHINE_STATUS: "Report the machine's current state and its readings.",
    Intent.PRODUCTION_ANALYSIS: (
        "State how far below or above plan production was, then the main reason with its "
        "size, then the secondary factor."
    ),
    Intent.MAINTENANCE_ATTENTION: (
        'Open with a complete sentence in the form "<machine> needs attention first." '
        "Give the reading and the limit it exceeds, and recommend inspection. Finish with "
        "a sentence saying this is a rule-based threshold check, not predictive maintenance."
    ),
}


def build_fact_sheet(run: AgentRun) -> str:
    """Every fact the answer may use, and nothing else."""
    lines: list[str] = [f"Question: {run.question}"]
    if run.rewritten_question and run.rewritten_question != run.question:
        lines.append(f"Interpreted as: {run.rewritten_question}")
    if run.window is not None:
        lines.append(
            f"Period: {run.window.start} to {run.window.end} ({run.window.label}, "
            f"{run.window.days} day(s))"
        )

    if run.headline is not None:
        value = run.headline.text or (
            f"{run.headline.value:g} {run.headline.unit}".strip()
            if run.headline.value is not None
            else ""
        )
        if value:
            lines.append("")
            lines.append(f"RESULT — {run.headline.label}: {value}")

    if run.capacity is not None:
        cap = run.capacity
        lines.append("")
        lines.append(f"Capacity for {cap.part_id}: {cap.final_capacity} units (the total)")
        lines.append(f"  cycle time: {cap.cycle_time_min:g} minutes per part")
        lines.append(f"  machine limit: {cap.machine_capacity} units")
        if cap.material_capacity is not None:
            lines.append(
                f"  material limit: {cap.material_capacity} units "
                f"({cap.available_quantity:g} of {cap.material_id})"
            )
        lines.append(f"  binding constraint: {cap.binding_constraint}")
        for machine in cap.machines:
            if machine.eligible:
                lines.append(
                    f"  {machine.machine_id}: {machine.effective_hours:g} available hours "
                    f"({machine.planned_hours:g} planned − {machine.maintenance_hours:g} "
                    f"maintenance) → {machine.parts_possible} units"
                )

    if run.constraint is not None:
        lines.append(f"  constraint finding: {run.constraint.explanation}")

    if run.health:
        lines.append("")
        for health in run.health[: 5 if len(run.health) > 1 else 1]:
            verdict = (
                "can continue production" if health.can_produce else "cannot continue production"
            )
            lines.append(f"{health.machine_id}: status {health.status}, {verdict}")
            for check in health.checks:
                lines.append(f"  {check.verdict}")
            if health.attention_note:
                lines.append(f"  attention: {health.attention_note}")

    if run.analysis is not None:
        a = run.analysis
        lines.append("")
        lines.append(
            f"Production versus plan: planned {a.planned_quantity}, produced "
            f"{a.produced_quantity}, rejected {a.rejected_quantity} of {a.processed_quantity} "
            f"processed"
        )
        if a.pct_below_plan is not None:
            lines.append(f"  {a.pct_below_plan:g}% below plan (shortfall {a.shortfall} units)")
        if a.reject_rate_pct is not None:
            lines.append(f"  reject rate: {a.reject_rate_pct:g}%")
        for factor in a.factors:
            lines.append(f"  factor: {factor.detail}")

    evidence = [
        f"  {s.title}: {s.summary}"
        for s in run.steps
        if s.status is StepStatus.OK and s.kind == "tool" and s.summary
    ]
    if evidence:
        lines.append("")
        lines.append("Retrieved from the MES:")
        lines.extend(evidence)

    if run.missing_fields:
        lines.append("")
        lines.append("Unavailable data:")
        lines.extend(f"  {m.field} for {m.entity}: {m.reason}" for m in run.missing_fields)

    unknown = run.understanding.entities.unknown if run.understanding is not None else []
    if unknown:
        lines.append("")
        lines.extend(f"{e.id} does not exist in the MES." for e in unknown)

    return "\n".join(lines)


def should_explain(run: AgentRun) -> bool:
    """A rejection and a clarification are already the final word.

    The out-of-domain message is fixed by requirement (FR-9) and must not be
    paraphrased; a clarifying question is one sentence the pipeline already
    chose. Neither needs a model.
    """
    return run.status in (RunStatus.ANSWERED, RunStatus.REFUSED_MISSING_DATA)


async def explain(
    run: AgentRun, llm: LLMClient, *, correction: str | None = None
) -> tuple[str, LLMUsage]:
    """Write the answer. `correction` feeds a failed grounding check back in."""
    shape = _SHAPE.get(run.intent, "Answer the question directly from the facts.")
    facts = build_fact_sheet(run)

    if run.status is RunStatus.REFUSED_MISSING_DATA:
        shape = (
            "Say plainly that the figure cannot be calculated, and name exactly which "
            "information is unavailable. Do not estimate or suggest a substitute value."
        )

    user = f"{shape}\n\nFACTS\n-----\n{facts}"
    if correction:
        user += (
            f"\n\nYour previous answer was rejected because {correction}. "
            "Write it again using only the figures listed above."
        )

    text, usage = await llm.complete(system=_SYSTEM, user=user, max_tokens=400)
    return text.strip(), usage
