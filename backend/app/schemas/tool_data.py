"""Payload shapes returned inside ToolResult.data, one per MES tool."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from app.schemas.mes import (
    InventoryItem,
    MachineAvailability,
    MachineStatus,
    MaintenanceEvent,
    OrderTotals,
    Part,
    ProductionHistoryRow,
    ProductionOrder,
    ProductionTotals,
    RuleThreshold,
)


class MachineStatusData(BaseModel):
    machines: list[MachineStatus] = Field(default_factory=list)
    thresholds: list[RuleThreshold] = Field(
        default_factory=list,
        description=(
            "Health limits from rule_thresholds, so a verdict can name what it compared against"
        ),
    )
    known_machine_ids: list[str] | None = Field(
        default=None,
        description="Populated only when a requested machine does not exist (scenario R5)",
    )


class AvailabilityData(BaseModel):
    machine_type: str | None = None
    machines: list[MachineAvailability] = Field(default_factory=list)
    eligible_machine_ids: list[str] = Field(default_factory=list)
    total_effective_hours: float = 0.0


class PartInformationData(BaseModel):
    part: Part | None = None
    known_part_ids: list[str] | None = None


class ProductionOrdersData(BaseModel):
    orders: list[ProductionOrder] = Field(default_factory=list)
    totals: OrderTotals = Field(default_factory=OrderTotals)


class MaterialInventoryData(BaseModel):
    items: list[InventoryItem] = Field(default_factory=list)
    known_material_ids: list[str] | None = None


class MaintenanceScheduleData(BaseModel):
    events: list[MaintenanceEvent] = Field(default_factory=list)
    hours_by_machine: dict[str, float] = Field(
        default_factory=dict,
        description="Scheduled or in-progress hours per machine inside the window",
    )
    machines_under_maintenance_today: list[str] = Field(
        default_factory=list,
        description="Machines with maintenance active today, regardless of the requested window",
    )


class ProductionHistoryData(BaseModel):
    rows: list[ProductionHistoryRow] = Field(default_factory=list)
    totals: ProductionTotals = Field(default_factory=ProductionTotals)
    totals_by_machine: dict[str, ProductionTotals] = Field(default_factory=dict)
    last_production_day: date | None = Field(
        default=None,
        description=(
            "Most recent day with any recorded production, so 'yesterday' can fall back sensibly"
        ),
    )
