"""The deterministic engine (FR-6, ADR-3, acceptance criterion 4).

Pure functions, so these tests need no database and assert exact integers. If
any of them fail, a number in the demo is wrong.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.engine import (
    CapacityUnavailable,
    analyse_production,
    calculate_capacity,
    evaluate_machine,
    identify_constraint,
    rank_attention,
)
from app.schemas.mes import (
    InventoryItem,
    MachineAvailability,
    MachineStatus,
    Part,
    ProductionHistoryRow,
    RuleThreshold,
)

A12 = Part(
    part_id="A12",
    part_name="A12 Bearing",
    material_id="STEEL-4140",
    material_qty_per_unit=1.0,
    cycle_time_min=3.5,
    required_machine_type="CNC_LATHE",
)
STEEL = InventoryItem(
    material_id="STEEL-4140", material_name="Steel 4140", unit="pcs", available_quantity=9600.0
)


def machine(machine_id, planned, maintenance, *, status="running", eligible=True):
    return MachineAvailability(
        machine_id=machine_id,
        machine_name=machine_id,
        machine_type="CNC_LATHE",
        status=status,
        eligible=eligible,
        ineligible_reason=None if eligible else f"status is '{status}'",
        planned_hours=planned,
        maintenance_hours=maintenance,
        effective_hours=max(0.0, planned - maintenance),
    )


THRESHOLDS = [
    RuleThreshold(
        rule_key="machine.temperature_c",
        display_name="Spindle temperature",
        unit="°C",
        warning_threshold=70,
        critical_threshold=85,
    ),
    RuleThreshold(
        rule_key="machine.vibration_mm_s",
        display_name="Spindle vibration",
        unit="mm/s",
        warning_threshold=2.5,
        critical_threshold=4.0,
    ),
]


def status(machine_id, *, state="running", temp=60.0, vib=1.0):
    return MachineStatus(
        machine_id=machine_id,
        machine_name=machine_id,
        machine_type="CNC_LATHE",
        status=state,
        temperature_c=temp,
        vibration_mm_s=vib,
    )


# ------------------------------------------------------------------- capacity


def test_the_seeded_hero_figure():
    """The documented Tuesday number: 72/72/50 effective hours at a 3.5 min cycle."""
    result = calculate_capacity(
        part=A12,
        availability=[
            machine("CNC-01", 72, 0),
            machine("CNC-02", 72, 0),
            machine("CNC-03", 72, 22),
        ],
        inventory=STEEL,
    )
    assert [m.parts_possible for m in result.machines] == [1234, 1234, 857]
    assert result.machine_capacity == 3325
    assert result.material_capacity == 9600
    assert result.final_capacity == 3325
    assert result.binding_constraint == "machine"


def test_the_floor_is_applied_per_machine_not_to_the_total():
    """Three machines each wasting 5 minutes waste it individually."""
    fleet = [machine(f"CNC-0{i}", 1.0, 0.0) for i in (1, 2, 3)]  # 60 min each
    result = calculate_capacity(part=A12, availability=fleet, inventory=STEEL)
    assert [m.parts_possible for m in result.machines] == [17, 17, 17]  # floor(60/3.5) = 17
    assert result.machine_capacity == 51, "not floor(180/3.5) = 51 by luck — check the reasoning"

    # A case where the two differ: 3 machines × 20 min at 6 min/part.
    part = A12.model_copy(update={"cycle_time_min": 7.0})
    fleet = [machine(f"CNC-0{i}", 20 / 60, 0.0) for i in (1, 2, 3)]  # 20 min each
    per_machine = calculate_capacity(part=part, availability=fleet, inventory=STEEL)
    assert [m.parts_possible for m in per_machine.machines] == [2, 2, 2]
    assert per_machine.machine_capacity == 6, "60 min pooled would give 8; machines do not pool"


def test_maintenance_reduces_available_hours():
    without = calculate_capacity(part=A12, availability=[machine("CNC-03", 72, 0)], inventory=STEEL)
    with_maint = calculate_capacity(
        part=A12, availability=[machine("CNC-03", 72, 22)], inventory=STEEL
    )
    assert without.final_capacity == 1234
    assert with_maint.final_capacity == 857


def test_maintenance_longer_than_the_shift_floors_at_zero():
    result = calculate_capacity(part=A12, availability=[machine("CNC-03", 8, 20)], inventory=STEEL)
    assert result.machines[0].effective_hours == 0
    assert result.final_capacity == 0


def test_material_binds_when_stock_is_short():
    scarce = InventoryItem(
        material_id="STEEL-4140", material_name="Steel", unit="pcs", available_quantity=180.0
    )
    result = calculate_capacity(part=A12, availability=[machine("CNC-01", 72, 0)], inventory=scarce)
    assert result.machine_capacity == 1234
    assert result.material_capacity == 180
    assert result.final_capacity == 180
    assert result.binding_constraint == "material"


def test_material_consumption_above_one_per_part():
    part = A12.model_copy(update={"material_qty_per_unit": 1.2})
    stock = InventoryItem(
        material_id="STEEL-4140", material_name="Steel", unit="pcs", available_quantity=100.0
    )
    result = calculate_capacity(part=part, availability=[machine("CNC-01", 72, 0)], inventory=stock)
    assert result.material_capacity == 83  # floor(100 / 1.2)


def test_ineligible_machines_contribute_nothing():
    result = calculate_capacity(
        part=A12,
        availability=[
            machine("CNC-01", 72, 0),
            machine("CNC-02", 72, 0, status="maintenance", eligible=False),
        ],
        inventory=STEEL,
    )
    assert result.eligible_machine_ids == ["CNC-01"]
    assert result.machine_capacity == 1234
    assert result.machines[1].parts_possible == 0


def test_the_working_is_shown():
    """The formula is what lets the answer justify itself."""
    result = calculate_capacity(part=A12, availability=[machine("CNC-03", 72, 22)], inventory=STEEL)
    working = " ".join(result.formula)
    assert "72 planned − 22 maintenance = 50 h" in working
    assert "floor(50 × 60 ÷ 3.5) = 857" in working
    assert "min(857, 9600) = 857" in working


@pytest.mark.parametrize(
    ("part_change", "expected_field"),
    [
        ({"cycle_time_min": None}, "parts.cycle_time_min"),
        ({"material_qty_per_unit": None}, "parts.material_qty_per_unit"),
    ],
)
def test_a_missing_input_refuses_and_names_the_field(part_change, expected_field):
    part = A12.model_copy(update=part_change)
    with pytest.raises(CapacityUnavailable) as exc:
        calculate_capacity(part=part, availability=[machine("CNC-01", 72, 0)], inventory=STEEL)
    assert exc.value.field == expected_field


def test_uncounted_stock_refuses_rather_than_assuming_zero():
    unknown = InventoryItem(
        material_id="STEEL-1045", material_name="Steel", unit="pcs", available_quantity=None
    )
    with pytest.raises(CapacityUnavailable) as exc:
        calculate_capacity(part=A12, availability=[machine("CNC-01", 72, 0)], inventory=unknown)
    assert exc.value.field == "inventory.available_quantity"


def test_no_eligible_machine_refuses():
    with pytest.raises(CapacityUnavailable):
        calculate_capacity(
            part=A12,
            availability=[machine("CNC-01", 72, 0, status="maintenance", eligible=False)],
            inventory=STEEL,
        )


# ----------------------------------------------------------------- bottleneck


def test_the_bottleneck_is_the_machine_with_the_fewest_hours():
    capacity = calculate_capacity(
        part=A12,
        availability=[
            machine("CNC-01", 72, 0),
            machine("CNC-02", 72, 0),
            machine("CNC-03", 72, 22),
        ],
        inventory=STEEL,
    )
    finding = identify_constraint(capacity)
    assert finding.kind == "machine"
    assert finding.bottleneck.machine_id == "CNC-03"
    assert finding.bottleneck.effective_hours == 50.0
    assert "maintenance" in finding.bottleneck.cause
    assert finding.bottleneck.margin_hours == 22.0
    assert [f.machine_id for f in finding.ranking] == ["CNC-03", "CNC-01", "CNC-02"]


def test_a_tie_is_not_a_bottleneck():
    """The honest answer on the last working day, when the fleet is level."""
    capacity = calculate_capacity(
        part=A12,
        availability=[machine("CNC-01", 8, 0), machine("CNC-02", 8, 0), machine("CNC-03", 8, 0)],
        inventory=STEEL,
    )
    finding = identify_constraint(capacity)
    assert finding.kind == "none"
    assert finding.bottleneck is None
    assert "No single bottleneck" in finding.explanation


def test_material_outranks_any_machine():
    scarce = InventoryItem(
        material_id="ALU-6061", material_name="Alu", unit="pcs", available_quantity=180.0
    )
    capacity = calculate_capacity(
        part=A12,
        availability=[machine("CNC-01", 72, 0), machine("CNC-03", 72, 22)],
        inventory=scarce,
    )
    finding = identify_constraint(capacity)
    assert finding.kind == "material"
    assert finding.bottleneck is None
    assert "Material is the limit" in finding.explanation


def test_a_machine_with_no_shifts_says_so():
    capacity = calculate_capacity(
        part=A12, availability=[machine("CNC-01", 72, 0), machine("CNC-03", 0, 0)], inventory=STEEL
    )
    finding = identify_constraint(capacity)
    assert finding.bottleneck.machine_id == "CNC-03"
    assert "no shifts planned" in finding.bottleneck.cause


# ------------------------------------------------------------- health rules


def test_a_healthy_machine_can_continue():
    health = evaluate_machine(status("CNC-03", temp=52.0, vib=1.8), THRESHOLDS)
    assert health.can_produce and health.breaches == 0
    assert health.fully_assessable
    assert "52 °C — Normal" in health.checks[0].verdict
    assert "70 °C limit" in health.checks[0].verdict


def test_a_warning_does_not_stop_production_but_is_reported():
    health = evaluate_machine(status("CNC-04", temp=66.5, vib=3.1), THRESHOLDS)
    assert health.can_produce is True
    assert health.breaches == 1
    assert health.checks[1].level == "warning"
    assert health.worst_relative_breach == pytest.approx(0.24)


def test_a_critical_reading_stops_production():
    health = evaluate_machine(status("CNC-04", temp=66.5, vib=4.5), THRESHOLDS)
    assert health.can_produce is False
    assert health.checks[1].level == "critical"


def test_maintenance_status_overrides_healthy_sensors():
    health = evaluate_machine(status("CNC-03", state="maintenance", temp=52.0, vib=1.8), THRESHOLDS)
    assert health.can_produce is False
    assert "maintenance" in health.reason


def test_maintenance_active_today_overrides_healthy_sensors():
    health = evaluate_machine(
        status("CNC-03", temp=52.0, vib=1.8), THRESHOLDS, under_maintenance_today=True
    )
    assert health.can_produce is False
    assert "maintenance active today" in health.reason


def test_a_missing_reading_is_never_healthy():
    health = evaluate_machine(status("CNC-02", temp=61.0, vib=None), THRESHOLDS)
    assert health.fully_assessable is False
    assert health.checks[1].level == "not_assessable"
    assert "not assessable" in health.checks[1].verdict
    assert "could not be assessed" in health.reason


def test_attention_ranking_breaks_ties_on_severity():
    """CNC-01 and CNC-04 each breach one limit; severity decides."""
    healths = [
        evaluate_machine(status("CNC-01", temp=72.5, vib=1.2), THRESHOLDS),
        evaluate_machine(status("CNC-02", temp=61.0, vib=None), THRESHOLDS),
        evaluate_machine(status("CNC-03", temp=52.0, vib=1.8), THRESHOLDS),
        evaluate_machine(status("CNC-04", temp=66.5, vib=3.1), THRESHOLDS),
    ]
    ranked = rank_attention(healths)
    assert [h.machine_id for h in ranked[:2]] == ["CNC-04", "CNC-01"]
    assert ranked[0].attention_note.startswith("Spindle vibration is 3.1 mm/s, 24% over")


def test_an_unreadable_sensor_is_flagged_but_not_ranked_above_a_real_breach():
    healths = [
        evaluate_machine(status("CNC-02", temp=61.0, vib=None), THRESHOLDS),
        evaluate_machine(status("CNC-04", temp=66.5, vib=3.1), THRESHOLDS),
    ]
    ranked = rank_attention(healths)
    assert ranked[0].machine_id == "CNC-04"
    unreadable = next(h for h in ranked if h.machine_id == "CNC-02")
    assert "unavailable" in unreadable.attention_note


# -------------------------------------------------------------- analysis (S4)


def rows(*specs):
    return [
        ProductionHistoryRow(
            machine_id=m,
            part_id="A12",
            production_date=date(2026, 9, 10),
            planned_quantity=p,
            produced_quantity=q,
            rejected_quantity=r,
            downtime_hours=d,
            downtime_reason=reason,
        )
        for m, p, q, r, d, reason in specs
    ]


INCIDENT = rows(
    ("CNC-01", 100, 97, 3, 0.0, None),
    ("CNC-02", 100, 64, 3, 2.1, "Tool changer fault - unplanned stop"),
    ("CNC-03", 50, 54, 2, 0.0, None),
)


def test_the_seeded_incident_percentages():
    analysis = analyse_production(INCIDENT, part_id="A12", cycle_time_min=3.5)
    assert analysis.shortfall == 35
    assert analysis.pct_below_plan == 14.0
    assert analysis.reject_rate_pct == 3.6
    assert analysis.parts_lost_to_downtime == 36


def test_factors_are_ranked_by_quantified_impact():
    """Downtime and rejects are comparable only once both are counted in parts."""
    analysis = analyse_production(INCIDENT, part_id="A12", cycle_time_min=3.5)
    assert [f.kind for f in analysis.factors] == ["downtime", "rejects", "offset"]
    assert analysis.factors[0].impact_parts == 36
    assert analysis.factors[1].impact_parts == 8
    assert analysis.factors[2].impact_parts == -4, "over-production offsets the shortfall"
    assert "CNC-02" in analysis.factors[0].machines


def test_the_downtime_reason_comes_from_the_record():
    analysis = analyse_production(INCIDENT, part_id="A12", cycle_time_min=3.5)
    assert "Tool changer fault" in analysis.factors[0].detail


def test_downtime_stays_unquantified_without_a_cycle_time():
    analysis = analyse_production(INCIDENT, part_id="B20", cycle_time_min=None)
    assert analysis.parts_lost_to_downtime is None
    downtime = next(f for f in analysis.factors if f.kind == "downtime")
    assert downtime.impact_parts == 0
    assert "cannot be quantified" in downtime.detail


def test_production_above_plan_is_reported_as_such():
    analysis = analyse_production(
        rows(("CNC-01", 100, 110, 2, 0.0, None)), part_id="A12", cycle_time_min=3.5
    )
    assert analysis.shortfall == -10
    assert "above plan" in analysis.summary


def test_no_rows_is_not_an_error():
    analysis = analyse_production([], part_id="A12", cycle_time_min=3.5)
    assert analysis.planned_quantity == 0
    assert analysis.factors == []
    assert "No production is recorded" in analysis.summary


def _line(machine_id, planned, maintenance=0.0, cycle=3.5):
    from app.engine.capacity import MachineCapacityLine

    effective = max(0.0, planned - maintenance)
    return MachineCapacityLine(
        machine_id=machine_id,
        status="running",
        eligible=True,
        planned_hours=planned,
        maintenance_hours=maintenance,
        effective_hours=effective,
        parts_possible=int(effective * 60 // cycle),
    )


def test_a_bottleneck_short_of_shifts_and_maintenance_names_both():
    """CNC-03 runs one shift and has its overhaul booked. Naming only the
    maintenance would send the manager to the smaller of the two problems."""
    from app.engine.bottleneck import _cause

    peers = [_line("CNC-01", 112), _line("CNC-02", 112), _line("CNC-03", 56, 24)]
    cause = _cause(peers[2], peers)
    assert (
        "shorter shift pattern (56 planned hours, against 112 planned hours on other machines)"
        in cause
    )
    assert "24 h of scheduled maintenance" in cause


def test_the_cause_reads_as_a_noun_phrase_after_because_of():
    """The explanation template is "because of {cause}". The first live run of the
    seven-day dataset printed "because of only 56 h of shifts are planned"."""
    from app.engine.bottleneck import _cause

    peers = [_line("CNC-01", 112), _line("CNC-03", 56)]
    sentence = f"because of {_cause(peers[1], peers)}"
    assert sentence.startswith("because of a shorter shift pattern")
    assert " are planned" not in sentence


def test_a_machine_with_nothing_taken_away_does_not_borrow_the_bottlenecks_cause():
    """The ranking described CNC-01 and CNC-02 as having "the fewest planned
    production hours" — true of neither."""
    from app.engine.bottleneck import _cause

    peers = [_line("CNC-01", 112), _line("CNC-02", 112), _line("CNC-03", 56)]
    assert _cause(peers[0], peers) == "no shift or maintenance reduction in this period"
    assert "fewest" not in _cause(peers[0], peers)
