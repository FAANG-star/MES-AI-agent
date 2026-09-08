"""Read models for the virtual MES.

These mirror the tables in db/schema.sql. Units are carried in the field names
(`cycle_time_min`, `temperature_c`, `vibration_mm_s`) so that neither a tool nor
a prompt can misread them — the same convention the schema uses.

Nothing here computes a verdict or a ratio. Tools return facts; the Day-6 engine
derives percentages, health verdicts and capacity from them. Keeping that split
is what makes acceptance criterion 4 ("numbers come from deterministic functions,
not the LLM") checkable.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

# The eligibility rule from docs/01-requirements.md §7, defined once so the tools
# and the Day-6 capacity engine cannot drift apart.
ELIGIBLE_MACHINE_STATUSES: frozenset[str] = frozenset({"running", "idle"})


class RuleThreshold(BaseModel):
    """A health limit held in the database, not in a prompt (ADR-4)."""

    rule_key: str
    display_name: str
    unit: str
    warning_threshold: float | None = None
    critical_threshold: float | None = None
    comparison: str = "gte"
    notes: str | None = None


class MachineStatus(BaseModel):
    machine_id: str
    machine_name: str
    machine_type: str
    status: str
    current_job: str | None = None
    available_hours: float | None = Field(
        default=None,
        description="Display only (ADR-7); capacity uses the shift calendar, never this column.",
    )
    temperature_c: float | None = None
    vibration_mm_s: float | None = None
    utilization_pct: float | None = None
    last_reading_at: datetime | None = None

    @property
    def is_eligible(self) -> bool:
        return self.status in ELIGIBLE_MACHINE_STATUSES


class MachineAvailability(BaseModel):
    """Hours a machine can actually produce in a window."""

    machine_id: str
    machine_name: str
    machine_type: str
    status: str
    eligible: bool
    ineligible_reason: str | None = None
    planned_hours: float = Field(
        description="Sum of machine_shift_calendar.planned_hours in the window"
    )
    maintenance_hours: float = Field(
        description="Scheduled or in-progress maintenance in the window"
    )
    effective_hours: float = Field(description="max(0, planned - maintenance)")


class Part(BaseModel):
    part_id: str
    part_name: str
    material_id: str | None = None
    material_qty_per_unit: float | None = None
    cycle_time_min: float | None = Field(
        default=None, description="Minutes of machine time per finished part; NULL means unknown"
    )
    required_machine_type: str
    standard_reject_pct: float | None = None


class ProductionOrder(BaseModel):
    order_id: str
    part_id: str
    planned_quantity: int
    completed_quantity: int
    remaining_quantity: int
    due_date: date
    status: str


class OrderTotals(BaseModel):
    orders: int = 0
    planned_quantity: int = 0
    completed_quantity: int = 0
    remaining_quantity: int = 0


class InventoryItem(BaseModel):
    material_id: str
    material_name: str
    unit: str
    available_quantity: float | None = Field(
        default=None, description="NULL means stock is unknown"
    )
    reorder_level: float | None = None
    below_reorder_level: bool | None = None
    updated_at: datetime | None = None


class MaintenanceEvent(BaseModel):
    maintenance_id: int
    machine_id: str
    maintenance_date: date
    duration_hours: float
    maintenance_type: str
    maintenance_status: str
    description: str | None = None


class ProductionHistoryRow(BaseModel):
    machine_id: str
    part_id: str
    production_date: date
    planned_quantity: int
    produced_quantity: int
    rejected_quantity: int
    downtime_hours: float
    downtime_reason: str | None = None


class ProductionTotals(BaseModel):
    """Raw sums only. Percentages are the Day-6 engine's job, not a tool's."""

    days: int = 0
    planned_quantity: int = 0
    produced_quantity: int = 0
    rejected_quantity: int = 0
    downtime_hours: float = 0.0
