"""Tool selection: turn an understood intent into an ordered, executable plan (FR-4).

How the choice is made matters, so it is worth being explicit.

The **model** decides what the manager is asking and which tools that needs; it
is given the live tool catalogue and returns its selection in
`ExtractedIntent.required_tools`. The **plan template** for each intent then
decides what runs: the tool sequence that intent's answer is built from, in the
order that satisfies each step's inputs.

Tools the model proposes beyond the template are **recorded, not run** (an
amendment to ADR-9). The live scenario matrix showed a local model adding
`get_production_history` to every bottleneck question. Nothing in a bottleneck
answer reads production history, so the extra call bought nothing and cost two
things: "Data Used" listed a table the answer never used, and every figure it
returned became a number the validator would accept in the prose — a wider
door for exactly the grounded-but-wrong sentences the validator exists to stop. See
`unused_proposals`.

The result is a plan that is reproducible run to run — the same question yields
the same steps, which is what makes a live demo safe.

Arguments that only exist after an earlier step are declared as bindings rather
than resolved here, so the plan is fully inspectable before anything executes.
"""

from __future__ import annotations

from app.agent.schemas import (
    ArgumentBinding,
    Intent,
    PlannedToolCall,
    ResolvedEntities,
)

# Intents that cannot be planned without knowing which part is meant.
PART_REQUIRED = {Intent.PRODUCTION_CAPACITY, Intent.BOTTLENECK}


def build_plan(
    *,
    intent: Intent,
    entities: ResolvedEntities,
    time_window: str,
) -> list[PlannedToolCall]:
    part_id = entities.parts[0].id if entities.parts else None
    machine_id = entities.machines[0].id if entities.machines else None

    steps: list[PlannedToolCall] = []

    def add(
        tool: str,
        title: str,
        reason: str,
        arguments: dict,
        bindings: list[ArgumentBinding] | None = None,
        requires: list[str] | None = None,
    ) -> None:
        steps.append(
            PlannedToolCall(
                step=len(steps) + 1,
                tool=tool,
                title=title,
                arguments={k: v for k, v in arguments.items() if v is not None},
                bindings=bindings or [],
                reason=reason,
                requires=requires or [],
            )
        )

    match intent:
        case Intent.PRODUCTION_CAPACITY | Intent.BOTTLENECK:
            add(
                "get_part_information",
                f"Get {part_id or 'part'} information",
                "The cycle time, material and required machine type drive every later step.",
                {"part_id": part_id},
                # Without a cycle time there is no capacity to calculate, and the
                # run must refuse rather than estimate (FR-8, scenario R3).
                requires=(
                    ["parts.cycle_time_min", "parts.material_qty_per_unit"]
                    if intent is Intent.PRODUCTION_CAPACITY
                    else ["parts.cycle_time_min"]
                ),
            )
            add(
                "get_available_machines",
                "Find eligible machines and their available hours",
                "Capacity depends on the hours each eligible machine can actually produce.",
                {"time_window": time_window},
                [
                    ArgumentBinding(
                        parameter="machine_type",
                        from_step=1,
                        source_path="data.part.required_machine_type",
                        description="Only machines of the type this part requires are eligible.",
                    )
                ],
            )
            add(
                "get_maintenance_schedule",
                "Check scheduled maintenance",
                "Planned maintenance removes hours from the window.",
                {"time_window": time_window},
            )
            if intent is Intent.PRODUCTION_CAPACITY:
                add(
                    "get_material_inventory",
                    "Check material availability",
                    "Final capacity is the lower of the machine and material limits.",
                    {},
                    [
                        ArgumentBinding(
                            parameter="material_id",
                            from_step=1,
                            source_path="data.part.material_id",
                            description="The material this part consumes.",
                        )
                    ],
                    requires=["inventory.available_quantity"],
                )
            add(
                "calculate_production_capacity",
                "Calculate capacity and identify the constraint",
                "The quantity is computed by the deterministic engine, never by the "
                "language model.",
                {"part_id": part_id, "time_window": time_window},
            )

        case Intent.MACHINE_HEALTH:
            add(
                "get_machine_status",
                f"Get {machine_id or 'machine'} status and condition thresholds",
                "Status and sensor readings, with the limits they are judged against.",
                {"machine_id": machine_id},
            )
            add(
                "get_maintenance_schedule",
                "Check whether maintenance is active",
                "A machine under maintenance cannot produce regardless of its readings.",
                {"machine_id": machine_id, "time_window": time_window},
            )

        case Intent.MACHINE_STATUS:
            add(
                "get_machine_status",
                f"Get {machine_id or 'factory'} status",
                "Current operating status, job and sensor readings.",
                {"machine_id": machine_id},
            )

        case Intent.PRODUCTION_ANALYSIS:
            if part_id:
                # The cycle time is what converts downtime hours into parts, and
                # without that conversion the contributing factors cannot be
                # ranked against each other — an hour lost and a reject are not
                # comparable until both are expressed in units. Not `requires`:
                # a missing cycle time leaves the downtime unquantified rather
                # than refusing the whole analysis, which is the same field
                # being mandatory for capacity and optional here.
                add(
                    "get_part_information",
                    f"Get {part_id} information",
                    "The cycle time converts downtime hours into parts, so causes can be ranked.",
                    {"part_id": part_id},
                )
            add(
                "get_production_history",
                "Get recorded production",
                "Planned versus produced quantity, rejects and downtime for the period.",
                {"part_id": part_id, "time_window": time_window},
            )
            add(
                "get_production_orders",
                "Get the production plan",
                "What was supposed to be produced, to compare against what was.",
                {"part_id": part_id},
            )
            add(
                "get_maintenance_schedule",
                "Check maintenance and unplanned stops",
                "Corroborates a downtime reason against a second source.",
                {"time_window": time_window, "include_completed": True},
            )

        case Intent.MAINTENANCE_ATTENTION:
            add(
                "get_machine_status",
                "Get every machine's condition",
                "Readings for all machines, with the factory's thresholds.",
                {},
            )
            add(
                "get_maintenance_schedule",
                "Check what is already scheduled",
                "A machine with work already booked needs less attention than one without.",
                {"time_window": time_window},
            )

        case Intent.PRODUCTION_ORDERS:
            add(
                "get_production_orders",
                "Get production orders",
                "Planned versus completed quantity and due dates.",
                {"part_id": part_id, "time_window": time_window},
            )

        case Intent.MATERIAL_INVENTORY:
            add(
                "get_material_inventory",
                "Get material stock",
                "On-hand quantity and reorder levels.",
                {"material_id": entities.materials[0].id if entities.materials else None},
            )

    return steps


def missing_requirement(intent: Intent, entities: ResolvedEntities) -> str | None:
    """What stops this intent from being planned, if anything."""
    if intent in PART_REQUIRED and not entities.parts:
        return "part"
    return None


def unused_proposals(plan: list[PlannedToolCall], proposed: list[str] | None) -> list[str]:
    """Tools the model asked for that the plan for this intent does not run."""
    planned = {step.tool for step in plan}
    seen: list[str] = []
    for tool in proposed or []:
        if tool not in planned and tool not in seen:
            seen.append(tool)
    return seen
