"""The eight MES tools against the seeded factory.

These assert the behaviours the demo depends on: real values come back, unknown
entities are reported as unknown, NULLs surface as named missing fields, and
availability comes from the shift calendar rather than the display column.
"""

from __future__ import annotations

import pytest

from app.tools.registry import ToolNotImplementedError, UnknownToolError, registry
from tests.conftest import requires_db

pytestmark = requires_db


async def call(name, params, ctx):
    return await registry.invoke(name, params, ctx)


# ------------------------------------------------------------- registry shape


def test_all_eight_tools_from_fr5_are_registered():
    assert registry.names() == [
        "calculate_production_capacity",
        "get_available_machines",
        "get_machine_status",
        "get_maintenance_schedule",
        "get_material_inventory",
        "get_part_information",
        "get_production_history",
        "get_production_orders",
    ]


def test_every_tool_exposes_an_llm_schema_with_described_parameters():
    for schema in registry.schemas():
        assert schema["description"]
        props = schema["input_schema"].get("properties", {})
        assert props, f"{schema['name']} exposes no parameters"
        for param, spec in props.items():
            assert spec.get("description"), f"{schema['name']}.{param} has no description"


async def test_unknown_tool_names_are_rejected(ctx):
    with pytest.raises(UnknownToolError):
        await call("drop_all_tables", {}, ctx)


# -------------------------------------------------------- get_machine_status


async def test_machine_status_returns_the_whole_factory_with_thresholds(ctx):
    r = await call("get_machine_status", {}, ctx)
    assert r.ok and len(r.data.machines) == 5
    assert {t.rule_key for t in r.data.thresholds} >= {
        "machine.temperature_c",
        "machine.vibration_mm_s",
    }
    assert {s.table for s in r.sources} == {"machines", "rule_thresholds"}


async def test_machine_status_reports_a_missing_sensor_instead_of_calling_it_healthy(ctx):
    r = await call("get_machine_status", {}, ctx)
    missing = {(m.entity, m.field) for m in r.missing_fields}
    assert ("CNC-02", "machines.vibration_mm_s") in missing
    assert r.warnings


async def test_machine_status_for_one_machine(ctx):
    r = await call("get_machine_status", {"machine_id": "CNC-03"}, ctx)
    m = r.data.machines[0]
    assert (m.machine_id, m.machine_type) == ("CNC-03", "CNC_LATHE")
    assert m.temperature_c == 52.0 and m.vibration_mm_s == 1.8
    assert m.is_eligible


async def test_unknown_machine_is_reported_not_invented(ctx):
    r = await call("get_machine_status", {"machine_id": "CNC-09"}, ctx)
    assert r.not_found == ["CNC-09"]
    assert r.data.machines == []
    assert r.data.known_machine_ids == ["CNC-01", "CNC-02", "CNC-03", "CNC-04", "CNC-05"]


# ---------------------------------------------------- get_available_machines


async def test_available_machines_uses_the_shift_calendar_minus_maintenance(ctx):
    r = await call(
        "get_available_machines", {"machine_type": "CNC_LATHE", "time_window": "this_week"}, ctx
    )
    machines = {m.machine_id: m for m in r.data.machines}
    assert set(machines) == {"CNC-01", "CNC-02", "CNC-03"}
    for m in machines.values():
        assert m.effective_hours == pytest.approx(max(0.0, m.planned_hours - m.maintenance_hours))
    assert r.window.start <= r.window.end
    assert {s.table for s in r.sources} >= {"machine_shift_calendar", "maintenance"}


async def test_maintenance_makes_cnc03_the_least_available_lathe(ctx):
    r = await call(
        "get_available_machines", {"machine_type": "CNC_LATHE", "time_window": "this_week"}, ctx
    )
    m = {x.machine_id: x for x in r.data.machines}
    assert m["CNC-03"].maintenance_hours > 0
    assert m["CNC-03"].effective_hours < m["CNC-01"].effective_hours
    assert m["CNC-03"].effective_hours < m["CNC-02"].effective_hours


async def test_eligibility_follows_the_documented_status_rule(ctx):
    r = await call("get_available_machines", {}, ctx)
    for m in r.data.machines:
        assert m.eligible == (m.status in {"running", "idle"})
        if not m.eligible:
            assert m.ineligible_reason


async def test_unknown_machine_type_lists_the_real_ones(ctx):
    r = await call("get_available_machines", {"machine_type": "LASER"}, ctx)
    assert r.not_found == ["LASER"]
    assert "CNC_LATHE" in r.warnings[0]


# ------------------------------------------------------ get_part_information


async def test_part_information_returns_cycle_time_and_routing(ctx):
    r = await call("get_part_information", {"part_id": "A12"}, ctx)
    part = r.data.part
    assert part.cycle_time_min == 3.5
    assert part.required_machine_type == "CNC_LATHE"
    assert part.material_id == "STEEL-4140"
    assert r.missing_fields == []


async def test_missing_cycle_time_is_named_so_capacity_can_be_refused(ctx):
    r = await call("get_part_information", {"part_id": "B20"}, ctx)
    assert r.data.part.cycle_time_min is None
    fields = {m.field for m in r.missing_fields}
    assert "parts.cycle_time_min" in fields
    assert r.has_missing_data


async def test_unknown_part_is_reported_not_invented(ctx):
    r = await call("get_part_information", {"part_id": "ZZ9"}, ctx)
    assert r.not_found == ["ZZ9"] and r.data.part is None
    assert r.data.known_part_ids == ["A12", "B20", "C15"]


# ------------------------------------------------------ get_production_orders


async def test_production_orders_expose_remaining_quantity(ctx):
    r = await call("get_production_orders", {"part_id": "A12"}, ctx)
    assert r.data.orders
    for o in r.data.orders:
        assert o.remaining_quantity == o.planned_quantity - o.completed_quantity
    assert r.data.totals.orders == len(r.data.orders)


async def test_production_orders_filter_by_status(ctx):
    r = await call("get_production_orders", {"status": "in_progress"}, ctx)
    assert r.data.orders and all(o.status == "in_progress" for o in r.data.orders)


# ----------------------------------------------------- get_material_inventory


async def test_inventory_flags_stock_below_reorder_level(ctx):
    r = await call("get_material_inventory", {"material_id": "ALU-6061"}, ctx)
    item = r.data.items[0]
    assert item.available_quantity == 180.0
    assert item.below_reorder_level is True


async def test_uncounted_stock_is_unknown_not_zero(ctx):
    r = await call("get_material_inventory", {"material_id": "STEEL-1045"}, ctx)
    assert r.data.items[0].available_quantity is None
    assert r.data.items[0].below_reorder_level is None
    assert {m.field for m in r.missing_fields} == {"inventory.available_quantity"}


# --------------------------------------------------- get_maintenance_schedule


async def test_maintenance_schedule_totals_hours_per_machine(ctx):
    r = await call("get_maintenance_schedule", {"time_window": "this_week"}, ctx)
    assert r.data.hours_by_machine.get("CNC-03", 0) > 0
    for e in r.data.events:
        assert e.maintenance_status in {"scheduled", "in_progress"}
        assert r.window.contains(e.maintenance_date)


async def test_active_maintenance_today_is_independent_of_the_window(ctx):
    """Scenario S2 depends on this: CNC-03 has work scheduled later this week but
    nothing active today, so it can keep running now."""
    r = await call(
        "get_maintenance_schedule", {"machine_id": "CNC-03", "time_window": "next_week"}, ctx
    )
    assert "CNC-03" not in r.data.machines_under_maintenance_today


async def test_completed_maintenance_is_excluded_unless_asked_for(ctx):
    without = await call("get_maintenance_schedule", {"time_window": "last_week"}, ctx)
    with_done = await call(
        "get_maintenance_schedule", {"time_window": "last_week", "include_completed": True}, ctx
    )
    assert len(with_done.data.events) >= len(without.data.events)


# ----------------------------------------------------- get_production_history


async def test_production_history_returns_raw_totals_only(ctx):
    r = await call("get_production_history", {"part_id": "A12", "time_window": "last_7_days"}, ctx)
    assert r.data.rows
    t = r.data.totals
    assert t.planned_quantity == sum(x.planned_quantity for x in r.data.rows)
    assert t.produced_quantity == sum(x.produced_quantity for x in r.data.rows)
    # Tools must not pre-compute ratios; the engine derives them on Day 6.
    assert not hasattr(t, "reject_rate_pct")


async def test_the_incident_day_matches_the_seeded_story(ctx):
    """The S4 numbers, read through the tool rather than straight from SQL."""
    probe = await call(
        "get_production_history", {"part_id": "A12", "time_window": "last_7_days"}, ctx
    )
    day = probe.data.last_production_day
    r = await call(
        "get_production_history", {"part_id": "A12", "time_window": f"{day}..{day}"}, ctx
    )
    t = r.data.totals
    assert (t.planned_quantity, t.produced_quantity, t.rejected_quantity) == (250, 215, 8)
    assert t.downtime_hours == 2.1
    assert r.data.totals_by_machine["CNC-02"].downtime_hours == 2.1
    reasons = {x.downtime_reason for x in r.data.rows if x.downtime_reason}
    assert reasons == {"Tool changer fault - unplanned stop"}


async def test_empty_history_says_when_production_last_happened(ctx):
    r = await call(
        "get_production_history", {"part_id": "A12", "time_window": "2020-01-01..2020-01-02"}, ctx
    )
    assert r.data.rows == []
    assert "most recent production day" in r.warnings[0]


# --------------------------------------------- calculate_production_capacity


async def test_capacity_tool_is_declared_but_fails_honestly_until_day_6(ctx):
    spec = registry.get("calculate_production_capacity")
    assert spec.implemented is False and "Day 6" in spec.planned_for
    with pytest.raises(ToolNotImplementedError):
        await call("calculate_production_capacity", {"part_id": "A12"}, ctx)


# ----------------------------------------------------------- window plumbing


async def test_bad_time_window_is_rejected_before_touching_the_database(ctx):
    from app.timewindow import WindowError

    with pytest.raises(WindowError):
        await call("get_available_machines", {"time_window": "next_quarter"}, ctx)


async def test_every_windowed_tool_reports_the_dates_it_used(ctx):
    for name in ("get_available_machines", "get_maintenance_schedule", "get_production_history"):
        r = await call(name, {"time_window": "this_week"}, ctx)
        assert r.window is not None and r.window.timezone == "Asia/Tokyo"
        assert r.elapsed_ms is not None
