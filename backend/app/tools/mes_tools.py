"""The eight MES tools (FR-5).

Each tool answers one factory question with facts and says exactly where they
came from. Three habits run through all of them:

  * **Facts, not verdicts.** A tool reports 3.1 mm/s and the 2.5 mm/s threshold;
    it does not decide "unhealthy". Ratios, capacities and rankings belong to the
    Day-6 engine, which keeps every derived number in deterministic Python
    (acceptance criterion 4).
  * **NULL is reported, never smoothed.** A missing cycle time becomes a
    `missing_fields` entry naming `parts.cycle_time_min`, which is what lets the
    agent refuse instead of estimating (FR-8).
  * **Everything is sourced.** Each result lists the tables, columns and entity
    ids it read, which becomes the "Data Used" panel (acceptance criterion 5).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.envelope import MissingField, SourceRef, ToolResult
from app.schemas.mes import OrderTotals, ProductionTotals
from app.schemas.tool_data import (
    AvailabilityData,
    MachineStatusData,
    MaintenanceScheduleData,
    MaterialInventoryData,
    PartInformationData,
    ProductionHistoryData,
    ProductionOrdersData,
)
from app.timewindow import WINDOW_LABELS, resolve_window
from app.tools.registry import ToolContext, registry

_WINDOW_HELP = (
    "Time window. One of: " + ", ".join(WINDOW_LABELS) + "; or an ISO date "
    "'YYYY-MM-DD'; or an ISO range 'YYYY-MM-DD..YYYY-MM-DD'. "
    "'this_week' means the remaining part of the current ISO week."
)


# --------------------------------------------------------------------- params


class GetMachineStatusParams(BaseModel):
    machine_id: str | None = Field(
        default=None,
        description="A machine id such as 'CNC-03'. Omit to get every machine in the factory.",
    )


class GetAvailableMachinesParams(BaseModel):
    machine_type: str | None = Field(
        default=None,
        description=(
            "Restrict to one machine type, e.g. 'CNC_LATHE'. Get this from "
            "get_part_information(part_id).required_machine_type when asking about a part."
        ),
    )
    time_window: str = Field(default="this_week", description=_WINDOW_HELP)


class GetPartInformationParams(BaseModel):
    part_id: str = Field(description="A part id such as 'A12', 'B20' or 'C15'.")


class GetProductionOrdersParams(BaseModel):
    part_id: str | None = Field(default=None, description="Restrict to one part, e.g. 'A12'.")
    status: str | None = Field(
        default=None,
        description=(
            "Restrict to one order status: planned, released, in_progress, completed, cancelled."
        ),
    )
    time_window: str | None = Field(
        default=None, description="Filter by due date. " + _WINDOW_HELP + " Omit for all orders."
    )


class GetMaterialInventoryParams(BaseModel):
    material_id: str | None = Field(
        default=None,
        description=(
            "A material id such as 'STEEL-4140'. Get it from "
            "get_part_information(part_id).material_id. Omit for all materials."
        ),
    )


class GetMaintenanceScheduleParams(BaseModel):
    machine_id: str | None = Field(
        default=None, description="Restrict to one machine, e.g. 'CNC-03'."
    )
    time_window: str = Field(default="this_week", description=_WINDOW_HELP)
    include_completed: bool = Field(
        default=False,
        description="Include finished maintenance. Useful when explaining a past shortfall.",
    )


class GetProductionHistoryParams(BaseModel):
    part_id: str | None = Field(default=None, description="Restrict to one part, e.g. 'A12'.")
    machine_id: str | None = Field(
        default=None, description="Restrict to one machine, e.g. 'CNC-02'."
    )
    time_window: str = Field(default="last_7_days", description=_WINDOW_HELP)


class CalculateProductionCapacityParams(BaseModel):
    part_id: str = Field(description="The part to calculate capacity for, e.g. 'A12'.")
    time_window: str = Field(default="this_week", description=_WINDOW_HELP)


# ---------------------------------------------------------------------- tools


@registry.tool(
    name="get_machine_status",
    description=(
        "Current status of one machine or all machines: operating status, spindle temperature, "
        "vibration, utilisation and the job loaded. Also returns the factory's health thresholds "
        "so a reading can be compared against the limit it must respect. Reports readings that are "
        "unavailable rather than treating them as normal."
    ),
    params_model=GetMachineStatusParams,
    scenarios=("S2", "S5", "Demo 1"),
)
async def get_machine_status(p: GetMachineStatusParams, ctx: ToolContext) -> ToolResult:
    machines = await ctx.repo.machines(p.machine_id)
    thresholds = await ctx.repo.thresholds()
    result: ToolResult[MachineStatusData] = ToolResult(tool="get_machine_status")

    if p.machine_id and not machines:
        known = await ctx.repo.machine_ids()
        result.not_found = [p.machine_id]
        result.data = MachineStatusData(thresholds=thresholds, known_machine_ids=known)
        result.warnings.append(f"Machine '{p.machine_id}' does not exist in the MES.")
        result.sources.append(SourceRef(table="machines", fields=["machine_id"], rows=0))
        return result

    for m in machines:
        if m.temperature_c is None:
            result.missing_fields.append(
                MissingField(
                    entity=m.machine_id,
                    field="machines.temperature_c",
                    reason="No temperature reading is recorded; the sensor is unavailable.",
                )
            )
        if m.vibration_mm_s is None:
            result.missing_fields.append(
                MissingField(
                    entity=m.machine_id,
                    field="machines.vibration_mm_s",
                    reason="No vibration reading is recorded; the sensor is unavailable.",
                )
            )

    result.data = MachineStatusData(machines=machines, thresholds=thresholds)
    result.sources = [
        SourceRef(
            table="machines",
            fields=[
                "status",
                "current_job",
                "temperature_c",
                "vibration_mm_s",
                "utilization_pct",
                "last_reading_at",
            ],
            keys=[m.machine_id for m in machines],
            rows=len(machines),
        ),
        SourceRef(
            table="rule_thresholds",
            fields=["warning_threshold", "critical_threshold"],
            keys=[t.rule_key for t in thresholds],
            rows=len(thresholds),
        ),
    ]
    if result.missing_fields:
        result.warnings.append(
            "Some sensor readings are unavailable; those machines cannot be fully assessed."
        )
    return result


@registry.tool(
    name="get_available_machines",
    description=(
        "Production hours available per machine over a time window: planned shift hours, hours "
        "lost "
        "to scheduled maintenance, and the effective hours that remain. Marks which machines are "
        "eligible to run work (status must be running or idle). This is the source of machine "
        "availability — not the machines.available_hours display column."
    ),
    params_model=GetAvailableMachinesParams,
    scenarios=("S1", "S3"),
)
async def get_available_machines(p: GetAvailableMachinesParams, ctx: ToolContext) -> ToolResult:
    window = resolve_window(p.time_window, ctx.clock)
    machines = await ctx.repo.availability(window.start, window.end, p.machine_type)
    result: ToolResult[AvailabilityData] = ToolResult(tool="get_available_machines", window=window)

    if p.machine_type and not machines:
        known = await ctx.repo.machine_types()
        result.not_found = [p.machine_type]
        result.warnings.append(
            f"No machine of type '{p.machine_type}' exists. Known types: {', '.join(known)}."
        )
        result.data = AvailabilityData(machine_type=p.machine_type)
        return result

    eligible = [m for m in machines if m.eligible]
    result.data = AvailabilityData(
        machine_type=p.machine_type,
        machines=machines,
        eligible_machine_ids=[m.machine_id for m in eligible],
        total_effective_hours=round(sum(m.effective_hours for m in eligible), 2),
    )
    result.sources = [
        SourceRef(
            table="machine_shift_calendar",
            fields=["planned_hours"],
            keys=[m.machine_id for m in machines],
            rows=len(machines),
        ),
        SourceRef(
            table="maintenance",
            fields=["duration_hours", "maintenance_status"],
            keys=[m.machine_id for m in machines if m.maintenance_hours > 0],
        ),
        SourceRef(
            table="machines",
            fields=["status", "machine_type"],
            keys=[m.machine_id for m in machines],
        ),
    ]
    if not eligible:
        result.warnings.append("No eligible machine is available in this window.")
    if all(m.planned_hours == 0 for m in machines) and machines:
        result.warnings.append(
            f"No shift hours are planned between {window.start} and {window.end} "
            "(the window may cover only non-working days)."
        )
    return result


@registry.tool(
    name="get_part_information",
    description=(
        "Master data for a manufactured part: cycle time in minutes per piece, the material it "
        "consumes and how much of it, the machine type it requires, and its standard reject rate. "
        "If the cycle time is unknown the tool says so explicitly — production capacity must not "
        "be "
        "calculated for that part."
    ),
    params_model=GetPartInformationParams,
    scenarios=("S1", "S3", "R3"),
)
async def get_part_information(p: GetPartInformationParams, ctx: ToolContext) -> ToolResult:
    part = await ctx.repo.part(p.part_id)
    result: ToolResult[PartInformationData] = ToolResult(tool="get_part_information")

    if part is None:
        known = await ctx.repo.part_ids()
        result.not_found = [p.part_id]
        result.data = PartInformationData(known_part_ids=known)
        result.warnings.append(f"Part '{p.part_id}' does not exist in the MES.")
        result.sources.append(SourceRef(table="parts", fields=["part_id"], rows=0))
        return result

    if part.cycle_time_min is None:
        result.missing_fields.append(
            MissingField(
                entity=part.part_id,
                field="parts.cycle_time_min",
                reason=(
                    "Cycle time has not been recorded for this part, so production capacity "
                    "cannot be calculated."
                ),
            )
        )
    if part.material_qty_per_unit is None:
        result.missing_fields.append(
            MissingField(
                entity=part.part_id,
                field="parts.material_qty_per_unit",
                reason=(
                    "Material consumption per part is not recorded, so material capacity "
                    "is unknown."
                ),
            )
        )

    result.data = PartInformationData(part=part)
    result.sources.append(
        SourceRef(
            table="parts",
            fields=[
                "cycle_time_min",
                "material_id",
                "material_qty_per_unit",
                "required_machine_type",
                "standard_reject_pct",
            ],
            keys=[part.part_id],
            rows=1,
        )
    )
    return result


@registry.tool(
    name="get_production_orders",
    description=(
        "Production orders with planned versus completed quantity, remaining quantity, due date "
        "and status. Use it to answer what was supposed to be produced, not what a machine could "
        "produce."
    ),
    params_model=GetProductionOrdersParams,
    scenarios=("S1", "S4"),
)
async def get_production_orders(p: GetProductionOrdersParams, ctx: ToolContext) -> ToolResult:
    window = resolve_window(p.time_window, ctx.clock) if p.time_window else None
    orders = await ctx.repo.orders(
        part_id=p.part_id,
        status=p.status,
        start=window.start if window else None,
        end=window.end if window else None,
    )
    totals = OrderTotals(
        orders=len(orders),
        planned_quantity=sum(o.planned_quantity for o in orders),
        completed_quantity=sum(o.completed_quantity for o in orders),
        remaining_quantity=sum(o.remaining_quantity for o in orders),
    )
    result: ToolResult[ProductionOrdersData] = ToolResult(
        tool="get_production_orders",
        window=window,
        data=ProductionOrdersData(orders=orders, totals=totals),
    )
    result.sources.append(
        SourceRef(
            table="production_orders",
            fields=["planned_quantity", "completed_quantity", "due_date", "status"],
            keys=[o.order_id for o in orders],
            rows=len(orders),
        )
    )
    if not orders:
        result.warnings.append("No production order matches these filters.")
    return result


@registry.tool(
    name="get_material_inventory",
    description=(
        "On-hand raw material stock, with the reorder level and whether stock has fallen below it. "
        "A material whose quantity has not been counted is reported as unknown, never as zero."
    ),
    params_model=GetMaterialInventoryParams,
    scenarios=("S1",),
)
async def get_material_inventory(p: GetMaterialInventoryParams, ctx: ToolContext) -> ToolResult:
    items = await ctx.repo.inventory(p.material_id)
    result: ToolResult[MaterialInventoryData] = ToolResult(tool="get_material_inventory")

    if p.material_id and not items:
        known = [i.material_id for i in await ctx.repo.inventory()]
        result.not_found = [p.material_id]
        result.data = MaterialInventoryData(known_material_ids=known)
        result.warnings.append(f"Material '{p.material_id}' does not exist in the MES.")
        return result

    for item in items:
        if item.available_quantity is None:
            result.missing_fields.append(
                MissingField(
                    entity=item.material_id,
                    field="inventory.available_quantity",
                    reason=(
                        "Stock quantity has not been recorded; a stock count may be in progress."
                    ),
                )
            )

    result.data = MaterialInventoryData(items=items)
    result.sources.append(
        SourceRef(
            table="inventory",
            fields=["available_quantity", "reorder_level", "unit"],
            keys=[i.material_id for i in items],
            rows=len(items),
        )
    )
    low = [i.material_id for i in items if i.below_reorder_level]
    if low:
        result.warnings.append(f"Below reorder level: {', '.join(low)}.")
    return result


@registry.tool(
    name="get_maintenance_schedule",
    description=(
        "Maintenance in a time window: each event with its date, duration and status, the total "
        "scheduled hours per machine, and which machines have maintenance active today. Scheduled "
        "and in-progress hours reduce the time a machine can produce."
    ),
    params_model=GetMaintenanceScheduleParams,
    scenarios=("S1", "S2", "S3", "S4", "S5"),
)
async def get_maintenance_schedule(p: GetMaintenanceScheduleParams, ctx: ToolContext) -> ToolResult:
    window = resolve_window(p.time_window, ctx.clock)
    statuses = (
        ("scheduled", "in_progress", "completed")
        if p.include_completed
        else ("scheduled", "in_progress")
    )
    events = await ctx.repo.maintenance(window.start, window.end, p.machine_id, statuses)

    hours: dict[str, float] = {}
    for e in events:
        if e.maintenance_status in ("scheduled", "in_progress"):
            hours[e.machine_id] = round(hours.get(e.machine_id, 0.0) + e.duration_hours, 2)

    # "Active today" is asked independently of the window, because "can this
    # machine run right now" must not depend on which week was requested.
    today = ctx.clock.today()
    today_events = await ctx.repo.maintenance(
        today, today, p.machine_id, ("scheduled", "in_progress")
    )

    result: ToolResult[MaintenanceScheduleData] = ToolResult(
        tool="get_maintenance_schedule",
        window=window,
        data=MaintenanceScheduleData(
            events=events,
            hours_by_machine=hours,
            machines_under_maintenance_today=sorted({e.machine_id for e in today_events}),
        ),
    )
    result.sources.append(
        SourceRef(
            table="maintenance",
            fields=["maintenance_date", "duration_hours", "maintenance_status", "maintenance_type"],
            keys=sorted({e.machine_id for e in events}),
            rows=len(events),
        )
    )
    if p.machine_id and not events:
        result.warnings.append(
            f"No maintenance is scheduled for {p.machine_id} between "
            f"{window.start} and {window.end}."
        )
    return result


@registry.tool(
    name="get_production_history",
    description=(
        "Recorded production per machine, part and day: planned quantity, produced quantity, "
        "rejected quantity, downtime hours and the recorded downtime reason. Returns raw totals "
        "only — deviations and reject rates are calculated by the rule engine, not stated here."
    ),
    params_model=GetProductionHistoryParams,
    scenarios=("S4",),
)
async def get_production_history(p: GetProductionHistoryParams, ctx: ToolContext) -> ToolResult:
    window = resolve_window(p.time_window, ctx.clock)
    rows = await ctx.repo.history(window.start, window.end, p.part_id, p.machine_id)
    last_day = await ctx.repo.last_production_day()

    totals = ProductionTotals(
        days=len({r.production_date for r in rows}),
        planned_quantity=sum(r.planned_quantity for r in rows),
        produced_quantity=sum(r.produced_quantity for r in rows),
        rejected_quantity=sum(r.rejected_quantity for r in rows),
        downtime_hours=round(sum(r.downtime_hours for r in rows), 2),
    )
    by_machine: dict[str, ProductionTotals] = {}
    for r in rows:
        t = by_machine.setdefault(r.machine_id, ProductionTotals())
        t.days += 1
        t.planned_quantity += r.planned_quantity
        t.produced_quantity += r.produced_quantity
        t.rejected_quantity += r.rejected_quantity
        t.downtime_hours = round(t.downtime_hours + r.downtime_hours, 2)

    result: ToolResult[ProductionHistoryData] = ToolResult(
        tool="get_production_history",
        window=window,
        data=ProductionHistoryData(
            rows=rows,
            totals=totals,
            totals_by_machine=by_machine,
            last_production_day=last_day,
        ),
    )
    result.sources.append(
        SourceRef(
            table="production_history",
            fields=[
                "planned_quantity",
                "produced_quantity",
                "rejected_quantity",
                "downtime_hours",
                "downtime_reason",
            ],
            keys=sorted({r.machine_id for r in rows}),
            rows=len(rows),
        )
    )
    if not rows:
        msg = f"No production is recorded between {window.start} and {window.end}"
        if last_day:
            msg += f"; the most recent production day is {last_day}"
        result.warnings.append(msg + ".")
    return result


# The eighth tool belongs to the contract but is built on Day 6 with the rest of
# the calculation engine. Declaring it here keeps the registry complete and makes
# an early call fail with a specific, honest error instead of a missing name.
registry.declare_planned(
    name="calculate_production_capacity",
    description=(
        "Maximum feasible production quantity for a part in a time window, from machine hours and "
        "material stock, with the binding constraint and the bottleneck machine. Deterministic: "
        "the "
        "number is computed in code, never by the language model."
    ),
    params_model=CalculateProductionCapacityParams,
    planned_for="Day 6 — calculation and rule engine",
    scenarios=("S1", "S3"),
)
