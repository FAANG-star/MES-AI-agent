"""Tool selection: turn an understood intent into an ordered, executable plan (FR-4).

How the choice is made matters, so it is worth being explicit.

The **model** decides what the manager is asking and which tools that needs; it
is given the live tool catalogue and returns its selection in
`ExtractedIntent.required_tools`. The **plan template** for each intent then
guarantees a floor: the tool sequence the demo scenarios depend on is always
present, in the order that satisfies each step's inputs. Anything extra the
model asked for and the registry recognises is appended; anything the registry
does not recognise was already dropped during extraction.

The result is a plan that is reproducible run to run — the same question yields
the same steps, which is what makes a live demo safe — while still letting the
model widen the query when a question genuinely needs more than the template.

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
from app.tools.registry import registry

# Intents that cannot be planned without knowing which part is meant.
PART_REQUIRED = {Intent.PRODUCTION_CAPACITY, Intent.BOTTLENECK}


def build_plan(
    *,
    intent: Intent,
    entities: ResolvedEntities,
    time_window: str,
    extra_tools: list[str] | None = None,
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
    ) -> None:
        steps.append(
            PlannedToolCall(
                step=len(steps) + 1,
                tool=tool,
                title=title,
                arguments={k: v for k, v in arguments.items() if v is not None},
                bindings=bindings or [],
                reason=reason,
            )
        )

    match intent:
        case Intent.PRODUCTION_CAPACITY | Intent.BOTTLENECK:
            add(
                "get_part_information",
                f"Get {part_id or 'part'} information",
                "The cycle time, material and required machine type drive every later step.",
                {"part_id": part_id},
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

    planned = {step.tool for step in steps}
    for tool in extra_tools or []:
        if tool in planned:
            continue
        # Only pass arguments the tool actually accepts — the registry is the
        # authority on that, so an extra step cannot be built with a parameter
        # the tool would reject.
        accepted = registry.get(tool).params_model.model_fields
        candidate = {"time_window": time_window, "part_id": part_id, "machine_id": machine_id}
        add(
            tool,
            f"Additional lookup: {tool}",
            "Selected by the language model as also relevant to this question.",
            {k: v for k, v in candidate.items() if k in accepted},
        )
        planned.add(tool)

    return steps


def missing_requirement(intent: Intent, entities: ResolvedEntities) -> str | None:
    """What stops this intent from being planned, if anything."""
    if intent in PART_REQUIRED and not entities.parts:
        return "part"
    return None
