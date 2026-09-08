"""Read-only SQL against the virtual MES.

Every statement here is fixed and parameterised. The repository returns typed
models; it makes no business decisions — eligibility, capacity, health verdicts
and ratios all live above it, so that the rules exist in exactly one place.

The one thing the SQL does compute is aggregation (SUM of shift hours, SUM of
maintenance hours), because that is set arithmetic the database does far better
than Python — and it is still deterministic, inspectable data, not a derived
business number.
"""

from __future__ import annotations

from datetime import date

import asyncpg

from app.db import fetch
from app.schemas.mes import (
    ELIGIBLE_MACHINE_STATUSES,
    InventoryItem,
    MachineAvailability,
    MachineStatus,
    MaintenanceEvent,
    Part,
    ProductionHistoryRow,
    ProductionOrder,
    RuleThreshold,
)


def _f(value) -> float | None:
    return None if value is None else float(value)


class MesRepository:
    """All factory reads. One instance per request is fine; it holds no state."""

    def __init__(self, pool: asyncpg.Pool | None = None) -> None:
        self._pool = pool

    async def _fetch(self, sql: str, *args) -> list[asyncpg.Record]:
        return await fetch(sql, *args, pool=self._pool)

    # ------------------------------------------------------------------ machines

    async def machines(self, machine_id: str | None = None) -> list[MachineStatus]:
        rows = await self._fetch(
            """
            SELECT machine_id, machine_name, machine_type, status::text AS status,
                   current_job, available_hours, temperature_c, vibration_mm_s,
                   utilization_pct, last_reading_at
              FROM machines
             WHERE ($1::text IS NULL OR machine_id = $1)
             ORDER BY machine_id
            """,
            machine_id,
        )
        return [
            MachineStatus(
                machine_id=r["machine_id"],
                machine_name=r["machine_name"],
                machine_type=r["machine_type"],
                status=r["status"],
                current_job=r["current_job"],
                available_hours=_f(r["available_hours"]),
                temperature_c=_f(r["temperature_c"]),
                vibration_mm_s=_f(r["vibration_mm_s"]),
                utilization_pct=_f(r["utilization_pct"]),
                last_reading_at=r["last_reading_at"],
            )
            for r in rows
        ]

    async def machine_ids(self) -> list[str]:
        rows = await self._fetch("SELECT machine_id FROM machines ORDER BY machine_id")
        return [r["machine_id"] for r in rows]

    async def availability(
        self, start: date, end: date, machine_type: str | None = None
    ) -> list[MachineAvailability]:
        """Planned, maintenance and effective hours per machine over a window.

        Availability comes from the shift calendar, never from
        machines.available_hours, which is a display field (ADR-7).
        """
        rows = await self._fetch(
            """
            WITH shift AS (
                SELECT machine_id, SUM(planned_hours) AS hours
                  FROM machine_shift_calendar
                 WHERE shift_date BETWEEN $1 AND $2
                 GROUP BY machine_id
            ),
            maint AS (
                SELECT machine_id, SUM(duration_hours) AS hours
                  FROM maintenance
                 WHERE maintenance_date BETWEEN $1 AND $2
                   AND maintenance_status IN ('scheduled', 'in_progress')
                 GROUP BY machine_id
            )
            SELECT m.machine_id, m.machine_name, m.machine_type, m.status::text AS status,
                   COALESCE(shift.hours, 0) AS planned_hours,
                   COALESCE(maint.hours, 0) AS maintenance_hours
              FROM machines m
              LEFT JOIN shift ON shift.machine_id = m.machine_id
              LEFT JOIN maint ON maint.machine_id = m.machine_id
             WHERE ($3::text IS NULL OR m.machine_type = $3)
             ORDER BY m.machine_id
            """,
            start,
            end,
            machine_type,
        )
        result: list[MachineAvailability] = []
        for r in rows:
            planned = float(r["planned_hours"])
            maint = float(r["maintenance_hours"])
            eligible = r["status"] in ELIGIBLE_MACHINE_STATUSES
            result.append(
                MachineAvailability(
                    machine_id=r["machine_id"],
                    machine_name=r["machine_name"],
                    machine_type=r["machine_type"],
                    status=r["status"],
                    eligible=eligible,
                    ineligible_reason=(
                        None
                        if eligible
                        else f"status is '{r['status']}', not one of "
                        f"{sorted(ELIGIBLE_MACHINE_STATUSES)}"
                    ),
                    planned_hours=planned,
                    maintenance_hours=maint,
                    effective_hours=max(0.0, planned - maint),
                )
            )
        return result

    async def machine_types(self) -> list[str]:
        rows = await self._fetch("SELECT DISTINCT machine_type FROM machines ORDER BY 1")
        return [r["machine_type"] for r in rows]

    # --------------------------------------------------------------------- parts

    async def part(self, part_id: str) -> Part | None:
        rows = await self._fetch(
            """
            SELECT part_id, part_name, material_id, material_qty_per_unit,
                   cycle_time_min, required_machine_type, standard_reject_pct
              FROM parts WHERE part_id = $1
            """,
            part_id,
        )
        if not rows:
            return None
        r = rows[0]
        return Part(
            part_id=r["part_id"],
            part_name=r["part_name"],
            material_id=r["material_id"],
            material_qty_per_unit=_f(r["material_qty_per_unit"]),
            cycle_time_min=_f(r["cycle_time_min"]),
            required_machine_type=r["required_machine_type"],
            standard_reject_pct=_f(r["standard_reject_pct"]),
        )

    async def part_ids(self) -> list[str]:
        rows = await self._fetch("SELECT part_id FROM parts ORDER BY part_id")
        return [r["part_id"] for r in rows]

    # -------------------------------------------------------------------- orders

    async def orders(
        self,
        part_id: str | None = None,
        status: str | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[ProductionOrder]:
        rows = await self._fetch(
            """
            SELECT order_id, part_id, planned_quantity, completed_quantity,
                   planned_quantity - completed_quantity AS remaining_quantity,
                   due_date, status::text AS status
              FROM production_orders
             WHERE ($1::text IS NULL OR part_id = $1)
               AND ($2::text IS NULL OR status::text = $2)
               AND ($3::date IS NULL OR due_date >= $3)
               AND ($4::date IS NULL OR due_date <= $4)
             ORDER BY due_date, order_id
            """,
            part_id,
            status,
            start,
            end,
        )
        return [ProductionOrder(**dict(r)) for r in rows]

    # ----------------------------------------------------------------- inventory

    async def inventory(self, material_id: str | None = None) -> list[InventoryItem]:
        rows = await self._fetch(
            """
            SELECT material_id, material_name, unit, available_quantity,
                   reorder_level, updated_at
              FROM inventory
             WHERE ($1::text IS NULL OR material_id = $1)
             ORDER BY material_id
            """,
            material_id,
        )
        items: list[InventoryItem] = []
        for r in rows:
            qty = _f(r["available_quantity"])
            reorder = _f(r["reorder_level"])
            items.append(
                InventoryItem(
                    material_id=r["material_id"],
                    material_name=r["material_name"],
                    unit=r["unit"],
                    available_quantity=qty,
                    reorder_level=reorder,
                    # Unknown stock stays unknown: no comparison is invented for it.
                    below_reorder_level=(None if qty is None or reorder is None else qty < reorder),
                    updated_at=r["updated_at"],
                )
            )
        return items

    # --------------------------------------------------------------- maintenance

    async def maintenance(
        self,
        start: date,
        end: date,
        machine_id: str | None = None,
        statuses: tuple[str, ...] = ("scheduled", "in_progress", "completed"),
    ) -> list[MaintenanceEvent]:
        rows = await self._fetch(
            """
            SELECT maintenance_id, machine_id, maintenance_date, duration_hours,
                   maintenance_type::text AS maintenance_type,
                   maintenance_status::text AS maintenance_status, description
              FROM maintenance
             WHERE maintenance_date BETWEEN $1 AND $2
               AND ($3::text IS NULL OR machine_id = $3)
               AND maintenance_status::text = ANY($4::text[])
             ORDER BY maintenance_date, machine_id, maintenance_id
            """,
            start,
            end,
            machine_id,
            list(statuses),
        )
        return [
            MaintenanceEvent(
                maintenance_id=r["maintenance_id"],
                machine_id=r["machine_id"],
                maintenance_date=r["maintenance_date"],
                duration_hours=float(r["duration_hours"]),
                maintenance_type=r["maintenance_type"],
                maintenance_status=r["maintenance_status"],
                description=r["description"],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------- history

    async def history(
        self,
        start: date,
        end: date,
        part_id: str | None = None,
        machine_id: str | None = None,
    ) -> list[ProductionHistoryRow]:
        rows = await self._fetch(
            """
            SELECT machine_id, part_id, production_date, planned_quantity,
                   produced_quantity, rejected_quantity, downtime_hours, downtime_reason
              FROM production_history
             WHERE production_date BETWEEN $1 AND $2
               AND ($3::text IS NULL OR part_id = $3)
               AND ($4::text IS NULL OR machine_id = $4)
             ORDER BY production_date, machine_id
            """,
            start,
            end,
            part_id,
            machine_id,
        )
        return [
            ProductionHistoryRow(
                machine_id=r["machine_id"],
                part_id=r["part_id"],
                production_date=r["production_date"],
                planned_quantity=r["planned_quantity"],
                produced_quantity=r["produced_quantity"],
                rejected_quantity=r["rejected_quantity"],
                downtime_hours=float(r["downtime_hours"]),
                downtime_reason=r["downtime_reason"],
            )
            for r in rows
        ]

    async def last_production_day(self) -> date | None:
        rows = await self._fetch("SELECT max(production_date) AS d FROM production_history")
        return rows[0]["d"] if rows else None

    # ---------------------------------------------------------------- thresholds

    async def thresholds(self) -> list[RuleThreshold]:
        rows = await self._fetch(
            """
            SELECT rule_key, display_name, unit, warning_threshold,
                   critical_threshold, comparison, notes
              FROM rule_thresholds ORDER BY rule_key
            """
        )
        return [
            RuleThreshold(
                rule_key=r["rule_key"],
                display_name=r["display_name"],
                unit=r["unit"],
                warning_threshold=_f(r["warning_threshold"]),
                critical_threshold=_f(r["critical_threshold"]),
                comparison=r["comparison"],
                notes=r["notes"],
            )
            for r in rows
        ]
