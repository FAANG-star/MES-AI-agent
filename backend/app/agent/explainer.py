"""Step 8: the model writes the answer, from facts it is given (FR-2, criterion 5).

The division of labour this whole prototype argues for lands here. The engine
has already decided every number. The explainer's only job is to put those
numbers into a sentence a factory manager would want to read.

So the model is handed a **fact sheet** rather than the raw run: a short,
explicit list of what was found. It is told not to calculate and not to
introduce a figure that is not on the sheet. Whatever it writes then goes
through `validator.py`, which checks that instruction was actually obeyed —
because when both local models were first asked to explain a capacity result,
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
points, no headings, no markdown, and no lists of facts strung together with commas.
- Never copy a label out of the facts. "RESULT —", "CNC-03 status:", "Reason:" and the \
like are how the facts are written down, not how an answer reads. Where the facts say \
"RESULT — Estimated A12 capacity: 3770 units", write a sentence such as "We can produce \
up to 3,770 A12 parts this week." — never the label form.
- The RESULT line is the answer. Make it unmistakable in your first sentence, in your \
own words, and never substitute a component of it, such as one machine's share of a total.
- Give the single most important reason for it.
- Answer the question that was actually asked, in wording that fits it. Two questions \
about the same machine are not the same question: one asks what it is doing, another \
whether it may keep running. Do not reach for a fixed phrasing you would use for any \
question — write the answer this one needs, from the facts listed.
- Name units exactly as the facts give them (units, hours, °C, mm/s, %).
- Write only the answer. Never repeat these instructions, the word FACTS, or a label \
such as "RESULT" back to the reader.

You are describing a result, not producing one."""

# What a good answer looks like for each scenario, taken from the demo script.
_SHAPE: dict[Intent, str] = {
    Intent.PRODUCTION_CAPACITY: (
        "State the total for that part and that period in your first sentence, written out "
        'as English — "We can produce up to N A12 parts this week." or "This week\'s A12 '
        'capacity is N parts." are both fine; a label followed by a colon is not. You must '
        "name the limiting machine and every cause the facts give for it. If it helps the manager "
        "trust the figure, say what the calculation took into account."
    ),
    Intent.BOTTLENECK: (
        "Say which machine constrains the part and how many production hours it has, then "
        "why. Where the facts rank the reasons, name the larger one first: naming only the "
        "smaller one is wrong even though it is real. Hours belong to the machine and "
        "parts to the output, so write that the machine *has* so many available production "
        "hours — never that the part's output is limited *to* a number of hours, and never "
        "that it is limited to this machine's own share of the total. Either of these "
        'reads correctly: "CNC-03 is the constraint on A12 this week: it has 28 available '
        "production hours against 96 on the other lathes, mainly because it runs a shorter "
        'shift pattern, with 20 h of scheduled maintenance on top." — or — "A12 is held '
        "back by CNC-03, which runs a single shift and so has only 28 of the 96 production "
        'hours the other lathes have; 20 h of maintenance takes the rest." Follow whichever '
        "fits the question asked, in your own words. "
        "If material is the limit instead of a machine, say that plainly. If the facts "
        "say there is no single bottleneck, say the machines are level and name them — "
        "do not pick one of them."
    ),
    Intent.MACHINE_HEALTH: (
        "The question is whether the machine may keep producing. Make that verdict "
        "unmistakable and give the readings that decided it, each against the limit the "
        "facts state. Say what the facts say about maintenance today, and nothing beyond "
        "them."
    ),
    Intent.MACHINE_STATUS: (
        "The question is what the machine is doing right now, not whether it is safe. "
        "Begin with a full sentence naming the machine and its state, then the job it is "
        "on if the facts name one, its utilisation and its readings. Do not turn it into a "
        "safety verdict unless the facts show a reading outside a limit."
    ),
    Intent.PRODUCTION_ANALYSIS: (
        "State how far below or above plan production was, then the main reason with its "
        "size, then the secondary factor."
    ),
    Intent.MAINTENANCE_ATTENTION: (
        "Make clear in your first sentence which machine needs attention first. Give the "
        "reading and the limit it exceeds, and recommend inspection. Finish with a "
        "sentence saying this is a rule-based threshold check, not predictive maintenance."
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
        found = run.constraint.bottleneck
        # Ranked, because an unranked pair invites the smaller one: asked what
        # slows A12 down, the model answered "because of scheduled maintenance"
        # while the shift pattern was taking more than twice as many hours.
        if found is not None and found.main_cause is not None:
            if found.shift_shortfall_hours > 0:
                lines.append(
                    f"  reason — shift pattern: {found.shift_shortfall_hours:g} h fewer planned "
                    f"than the other machines ({found.planned_hours:g} against "
                    f"{found.planned_hours + found.shift_shortfall_hours:g})"
                )
            if found.maintenance_hours > 0:
                lines.append(
                    f"  reason — maintenance: {found.maintenance_hours:g} h scheduled in this "
                    f"period"
                )
            lines.append(f"  the larger reason is the {found.main_cause}")

    if run.health:
        lines.append("")
        for health in run.health[: 5 if len(run.health) > 1 else 1]:
            verdict = (
                "can continue production" if health.can_produce else "cannot continue production"
            )
            lines.append(f"{health.machine_id}: status {health.status}, {verdict}")
            if health.current_job:
                lines.append(f"  current job: {health.current_job}")
            if health.utilization_pct is not None:
                lines.append(f"  utilisation: {health.utilization_pct:g}%")
            # Stated outright: with only a week's bookings in view, the
            # model wrote "maintenance is active" about a machine cleared to run.
            active = "maintenance active today" in health.reason.lower()
            lines.append(f"  maintenance active today: {'yes' if active else 'no'}")
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
        # Per machine, and with each factor's direction stated: given
        # only a total, the model attributed all 8 rejects to one machine, and
        # said the rejects "reduced the shortfall".
        for machine in a.by_machine:
            downtime = (
                f", downtime {machine.downtime_hours:g} hours" if machine.downtime_hours else ""
            )
            lines.append(
                f"  {machine.machine_id}: planned {machine.planned_quantity}, produced "
                f"{machine.produced_quantity}, rejected {machine.rejected_quantity}{downtime}"
            )
        for factor in a.factors:
            direction = (
                f"reduces the shortfall by {abs(factor.impact_parts)} parts"
                if factor.impact_parts < 0
                else f"adds {factor.impact_parts} parts to the shortfall"
            )
            lines.append(f"  factor: {factor.detail} ({direction})")

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
    run: AgentRun,
    llm: LLMClient,
    *,
    correction: str | None = None,
    temperature: float | None = None,
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

    text, usage = await llm.complete(
        system=_SYSTEM,
        user=user,
        max_tokens=400,
        temperature=temperature,
    )
    return text.strip(), usage
