"""The SQL oracle: the specification in docs/02-architecture.md §5, in SQL.

Shared by `tests/test_engine_oracle.py`, which requires the Python engine to
agree with it exactly, and by the scenario matrix, which checks every demo
answer against it. Keeping one copy is the point — two copies of an oracle
are two oracles, and they would drift.
"""

from __future__ import annotations

CAPACITY_ORACLE = """
WITH win AS (SELECT $1::date AS d_from, $2::date AS d_to),
part AS (SELECT * FROM parts WHERE part_id = $3),
eff AS (
    SELECT m.machine_id,
           m.status::text AS st,
           COALESCE((SELECT SUM(s.planned_hours) FROM machine_shift_calendar s, win w
                      WHERE s.machine_id = m.machine_id
                        AND s.shift_date BETWEEN w.d_from AND w.d_to), 0) AS planned_h,
           COALESCE((SELECT SUM(mt.duration_hours) FROM maintenance mt, win w
                      WHERE mt.machine_id = m.machine_id
                        AND mt.maintenance_date BETWEEN w.d_from AND w.d_to
                        AND mt.maintenance_status IN ('scheduled', 'in_progress')), 0) AS maint_h
      FROM machines m, part p
     WHERE m.machine_type = p.required_machine_type
)
SELECT
  (SELECT SUM(floor(GREATEST(0, e.planned_h - e.maint_h) * 60 / p.cycle_time_min))::int
     FROM eff e, part p WHERE e.st IN ('running', 'idle'))
       AS machine_capacity,
  (SELECT floor(i.available_quantity / p.material_qty_per_unit)::int
     FROM part p JOIN inventory i ON i.material_id = p.material_id)
       AS material_capacity,
  (SELECT e.machine_id FROM eff e WHERE e.st IN ('running', 'idle')
    ORDER BY GREATEST(0, e.planned_h - e.maint_h), e.machine_id LIMIT 1)
       AS bottleneck,
  (SELECT GREATEST(0, e.planned_h - e.maint_h) FROM eff e WHERE e.st IN ('running', 'idle')
    ORDER BY GREATEST(0, e.planned_h - e.maint_h), e.machine_id LIMIT 1)
       AS bottleneck_hours,
  (SELECT count(*) FROM eff e WHERE e.st IN ('running', 'idle')
     AND GREATEST(0, e.planned_h - e.maint_h) =
         (SELECT MIN(GREATEST(0, e2.planned_h - e2.maint_h)) FROM eff e2
           WHERE e2.st IN ('running', 'idle')))
       AS tied_at_minimum
"""

HEALTH_ORACLE = """
SELECT m.machine_id,
       COALESCE((m.temperature_c  >= t.warn)::int, 0)
         + COALESCE((m.vibration_mm_s >= v.warn)::int, 0)                   AS breaches,
       GREATEST(COALESCE((m.temperature_c  - t.warn) / t.warn,  -1),
                COALESCE((m.vibration_mm_s - v.warn) / v.warn, -1))         AS worst,
       (m.temperature_c IS NULL OR m.vibration_mm_s IS NULL)                AS not_assessable
  FROM machines m,
       (SELECT warning_threshold AS warn FROM rule_thresholds
         WHERE rule_key = 'machine.temperature_c')  t,
       (SELECT warning_threshold AS warn FROM rule_thresholds
         WHERE rule_key = 'machine.vibration_mm_s') v
 ORDER BY breaches DESC, not_assessable DESC, worst DESC
"""

ANALYSIS_ORACLE = """
SELECT SUM(planned_quantity)                                                   AS planned,
       SUM(produced_quantity)                                                  AS produced,
       SUM(rejected_quantity)                                                  AS rejected,
       SUM(downtime_hours)                                                     AS downtime_h,
       round(100.0 * (SUM(planned_quantity) - SUM(produced_quantity))
                   / NULLIF(SUM(planned_quantity), 0), 1)                      AS pct_below_plan,
       round(100.0 * SUM(rejected_quantity)
                   / NULLIF(SUM(produced_quantity) + SUM(rejected_quantity), 0), 1)
                                                                               AS reject_rate_pct,
       round(SUM(downtime_hours) * 60
             / (SELECT cycle_time_min FROM parts WHERE part_id = $2))          AS parts_lost
  FROM production_history
 WHERE part_id = $2 AND production_date = $1::date
"""
