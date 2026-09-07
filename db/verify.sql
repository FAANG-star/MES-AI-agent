-- =====================================================================
-- Day-2 data verification — independent oracle for the demo scenarios.
--
-- Recomputes in plain SQL what the Python engine must produce on Day 6.
-- If the engine and this file ever disagree, one of them is wrong.
--
--   make db-verify
-- =====================================================================

\if :{?demo_today}
\else
\set demo_today 'CURRENT_DATE'
\endif

\set QUIET on
\pset footer off

CREATE TEMP VIEW v_window AS
SELECT (:demo_today)::date                                AS d_from,   -- remaining part of the week
       (date_trunc('week', (:demo_today)::date)::date + 6) AS d_to;

-- Effective production hours per machine in the window: planned shift
-- hours minus maintenance that is still scheduled or in progress.
CREATE TEMP VIEW v_effective_hours AS
SELECT m.machine_id,
       m.machine_type,
       m.status,
       COALESCE(sc.h, 0)                              AS planned_h,
       COALESCE(mt.h, 0)                              AS maint_h,
       GREATEST(0, COALESCE(sc.h, 0) - COALESCE(mt.h, 0)) AS effective_h
  FROM machines m
  LEFT JOIN (SELECT s.machine_id, SUM(s.planned_hours) AS h
               FROM machine_shift_calendar s, v_window w
              WHERE s.shift_date BETWEEN w.d_from AND w.d_to
              GROUP BY s.machine_id) sc ON sc.machine_id = m.machine_id
  LEFT JOIN (SELECT mt.machine_id, SUM(mt.duration_hours) AS h
               FROM maintenance mt, v_window w
              WHERE mt.maintenance_date BETWEEN w.d_from AND w.d_to
                AND mt.maintenance_status IN ('scheduled', 'in_progress')
              GROUP BY mt.machine_id) mt ON mt.machine_id = m.machine_id;

-- The capacity formula from docs/02-architecture.md §5.
CREATE TEMP VIEW v_capacity AS
SELECT p.part_id,
       (SELECT SUM(floor(e.effective_h * 60 / p.cycle_time_min))::int
          FROM v_effective_hours e
         WHERE e.machine_type = p.required_machine_type
           AND e.status IN ('running', 'idle'))                     AS machine_capacity,
       floor(i.available_quantity / p.material_qty_per_unit)::int   AS material_capacity,
       (SELECT e.machine_id
          FROM v_effective_hours e
         WHERE e.machine_type = p.required_machine_type
           AND e.status IN ('running', 'idle')
         ORDER BY e.effective_h, e.machine_id LIMIT 1)              AS bottleneck_machine
  FROM parts p
  LEFT JOIN inventory i ON i.material_id = p.material_id;

-- Machine health against the thresholds stored in rule_thresholds.
CREATE TEMP VIEW v_health AS
SELECT m.machine_id,
       m.status,
       m.temperature_c,
       m.vibration_mm_s,
       (m.temperature_c IS NULL OR m.vibration_mm_s IS NULL)                          AS not_fully_assessable,
       (m.temperature_c  >= t.warn)::int + (m.vibration_mm_s >= v.warn)::int          AS breaches,
       GREATEST(COALESCE((m.temperature_c  - t.warn) / t.warn, -1),
                COALESCE((m.vibration_mm_s - v.warn) / v.warn, -1))::numeric(6,4)     AS worst_relative_breach,
       (SELECT count(*) FROM maintenance mt
         WHERE mt.machine_id = m.machine_id
           AND mt.maintenance_date = (SELECT d_from FROM v_window)
           AND mt.maintenance_status IN ('scheduled', 'in_progress'))                 AS active_maintenance_today
  FROM machines m,
       (SELECT warning_threshold AS warn FROM rule_thresholds WHERE rule_key = 'machine.temperature_c')  t,
       (SELECT warning_threshold AS warn FROM rule_thresholds WHERE rule_key = 'machine.vibration_mm_s') v;

-- The last production day, and the A12 plan-vs-actual on it.
CREATE TEMP VIEW v_last_day AS
SELECT max(production_date) AS d FROM production_history;

CREATE TEMP VIEW v_s4 AS
SELECT SUM(h.planned_quantity)                                                   AS planned,
       SUM(h.produced_quantity)                                                  AS produced,
       SUM(h.planned_quantity) - SUM(h.produced_quantity)                        AS shortfall,
       round(100.0 * (SUM(h.planned_quantity) - SUM(h.produced_quantity))
                   / SUM(h.planned_quantity), 1)                                 AS pct_below_plan,
       SUM(h.rejected_quantity)                                                  AS rejected,
       round(100.0 * SUM(h.rejected_quantity)
                   / (SUM(h.produced_quantity) + SUM(h.rejected_quantity)), 1)   AS reject_rate_pct,
       SUM(h.downtime_hours)                                                     AS downtime_h,
       round(SUM(h.downtime_hours) * 60
             / (SELECT cycle_time_min FROM parts WHERE part_id = 'A12'))         AS parts_lost_to_downtime
  FROM production_history h, v_last_day l
 WHERE h.part_id = 'A12' AND h.production_date = l.d;

\set QUIET off

\echo ''
\echo '=== ROW COUNTS ==================================================='
SELECT 'machines' AS "table", count(*) FROM machines
UNION ALL SELECT 'parts',                  count(*) FROM parts
UNION ALL SELECT 'inventory',              count(*) FROM inventory
UNION ALL SELECT 'production_orders',      count(*) FROM production_orders
UNION ALL SELECT 'machine_shift_calendar', count(*) FROM machine_shift_calendar
UNION ALL SELECT 'maintenance',            count(*) FROM maintenance
UNION ALL SELECT 'production_history',     count(*) FROM production_history
UNION ALL SELECT 'rule_thresholds',        count(*) FROM rule_thresholds
ORDER BY 1;

\echo ''
\echo '=== WINDOW ======================================================='
SELECT current_setting('TimeZone')                 AS factory_tz,
       (SELECT d_from FROM v_window)               AS today,
       to_char((SELECT d_from FROM v_window), 'Dy') AS dow,
       date_trunc('week', (SELECT d_from FROM v_window))::date AS week_start,
       (SELECT d_to FROM v_window)                 AS week_end,
       (SELECT d FROM v_last_day)                  AS last_production_day;

\echo ''
\echo '=== S1 / S3   A12 — effective hours per eligible machine ========='
SELECT e.machine_id, e.planned_h, e.maint_h, e.effective_h,
       floor(e.effective_h * 60 / p.cycle_time_min)::int AS parts_possible
  FROM v_effective_hours e, parts p
 WHERE p.part_id = 'A12'
   AND e.machine_type = p.required_machine_type
   AND e.status IN ('running', 'idle')
 ORDER BY e.effective_h, e.machine_id;

\echo ''
\echo '=== S1  capacity per part (A12 machine-bound · C15 material-bound)'
SELECT part_id, machine_capacity, material_capacity,
       LEAST(machine_capacity, material_capacity) AS final_capacity,
       CASE WHEN machine_capacity IS NULL THEN 'refuse: no cycle time'
            WHEN material_capacity < machine_capacity THEN 'material'
            ELSE 'machine' END                    AS binding_constraint,
       bottleneck_machine
  FROM v_capacity ORDER BY part_id;

\echo ''
\echo '=== S2 / S5   machine health vs rule_thresholds =================='
SELECT machine_id, status, temperature_c, vibration_mm_s, breaches,
       worst_relative_breach, not_fully_assessable, active_maintenance_today
  FROM v_health
 ORDER BY breaches DESC NULLS LAST, worst_relative_breach DESC;

\echo ''
\echo '=== S4  A12 on the last production day ==========================='
SELECT h.machine_id, h.planned_quantity, h.produced_quantity,
       h.rejected_quantity, h.downtime_hours, h.downtime_reason
  FROM production_history h, v_last_day l
 WHERE h.part_id = 'A12' AND h.production_date = l.d
 ORDER BY h.machine_id;

SELECT * FROM v_s4;

\echo ''
\echo '=== UI status strip =============================================='
SELECT machine_id, machine_name, status, current_job, available_hours,
       temperature_c, vibration_mm_s, utilization_pct
  FROM machines ORDER BY machine_id;

\echo ''
\echo '=== ASSERTIONS ==================================================='
CREATE TEMP VIEW v_checks (n, name, expected, actual) AS (
    SELECT  1, 'S1 A12 constraint is machine (not material)', 'machine',
            (SELECT CASE WHEN material_capacity < machine_capacity THEN 'material' ELSE 'machine' END
               FROM v_capacity WHERE part_id = 'A12')
    UNION ALL
    SELECT  2, 'S3 A12 bottleneck machine', 'CNC-03',
            (SELECT bottleneck_machine FROM v_capacity WHERE part_id = 'A12')
    UNION ALL
    SELECT  3, 'S3 bottleneck has strictly fewest effective hours', 'true',
            (SELECT (count(*) = 1)::text FROM (
                SELECT e.effective_h FROM v_effective_hours e, parts p
                 WHERE p.part_id = 'A12' AND e.machine_type = p.required_machine_type
                   AND e.status IN ('running', 'idle')
                 ORDER BY e.effective_h LIMIT 2) x
             WHERE x.effective_h = (SELECT min(e2.effective_h) FROM v_effective_hours e2, parts p2
                                     WHERE p2.part_id = 'A12' AND e2.machine_type = p2.required_machine_type
                                       AND e2.status IN ('running', 'idle')))
    UNION ALL
    SELECT  4, 'S1 A12 capacity is a positive integer', 'true',
            (SELECT (LEAST(machine_capacity, material_capacity) > 0)::text FROM v_capacity WHERE part_id = 'A12')
    UNION ALL
    SELECT  5, 'S1 variant C15 constraint is material', 'material',
            (SELECT CASE WHEN material_capacity < machine_capacity THEN 'material' ELSE 'machine' END
               FROM v_capacity WHERE part_id = 'C15')
    UNION ALL
    SELECT  6, 'R3 B20 has no cycle time (refusal path)', 'true',
            (SELECT (cycle_time_min IS NULL)::text FROM parts WHERE part_id = 'B20')
    UNION ALL
    SELECT  7, 'S2 CNC-03 is runnable today (status)', 'running',
            (SELECT status::text FROM machines WHERE machine_id = 'CNC-03')
    UNION ALL
    SELECT  8, 'S2 CNC-03 has no active maintenance today', '0',
            (SELECT active_maintenance_today::text FROM v_health WHERE machine_id = 'CNC-03')
    UNION ALL
    SELECT  9, 'S2 CNC-03 sensors are within thresholds', '0',
            (SELECT breaches::text FROM v_health WHERE machine_id = 'CNC-03')
    UNION ALL
    SELECT 10, 'S5 top attention machine', 'CNC-04',
            (SELECT machine_id FROM v_health
              ORDER BY breaches DESC NULLS LAST, worst_relative_breach DESC LIMIT 1)
    UNION ALL
    SELECT 11, 'S5 tie-break is exercised (2 machines, 1 breach each)', '2',
            (SELECT count(*)::text FROM v_health WHERE breaches = 1)
    UNION ALL
    SELECT 12, 'S5 one machine is not fully assessable (NULL sensor)', '1',
            (SELECT count(*)::text FROM v_health WHERE not_fully_assessable)
    UNION ALL
    SELECT 13, 'S4 A12 shortfall vs plan (%)', '14.0',
            (SELECT pct_below_plan::text FROM v_s4)
    UNION ALL
    SELECT 14, 'S4 reject rate (%)', '3.6', (SELECT reject_rate_pct::text FROM v_s4)
    UNION ALL
    SELECT 15, 'S4 downtime hours on the incident day', '2.10', (SELECT downtime_h::text FROM v_s4)
    UNION ALL
    SELECT 16, 'S4 downtime is corroborated by a maintenance record', '1',
            (SELECT count(*)::text FROM maintenance mt, v_last_day l
              WHERE mt.machine_id = 'CNC-02' AND mt.maintenance_date = l.d
                AND mt.maintenance_type = 'corrective')
    UNION ALL
    SELECT 17, 'S4 downtime explains the shortfall (within 5 parts)', 'true',
            (SELECT (abs(parts_lost_to_downtime - shortfall) <= 5)::text FROM v_s4)
    UNION ALL
    SELECT 18, 'Every machine has shift rows covering the whole week', '5',
            (SELECT count(*)::text FROM (
                SELECT s.machine_id FROM machine_shift_calendar s
                 WHERE s.shift_date BETWEEN date_trunc('week', (SELECT d_from FROM v_window))::date
                                        AND (SELECT d_to FROM v_window)
                 GROUP BY s.machine_id HAVING count(*) = 7) x)
    UNION ALL
    SELECT 19, 'Inventory has an unknown-stock row (missing-data path)', '1',
            (SELECT count(*)::text FROM inventory WHERE available_quantity IS NULL)
    UNION ALL
    SELECT 20, 'No maintenance outside the current week affects it', 'true',
            (SELECT (count(*) = 0)::text FROM maintenance mt, v_window w
              WHERE mt.maintenance_status IN ('scheduled', 'in_progress')
                AND mt.maintenance_date BETWEEN w.d_from AND w.d_to
                AND mt.machine_id <> 'CNC-03')
);

SELECT n, name, expected, actual,
       CASE WHEN actual IS NOT DISTINCT FROM expected THEN 'PASS' ELSE '*** FAIL ***' END AS result
  FROM v_checks ORDER BY n;

\echo ''
\echo '=== SUMMARY ======================================================'
SELECT count(*)                                                            AS checks,
       count(*) FILTER (WHERE actual IS NOT DISTINCT FROM expected)        AS passed,
       count(*) FILTER (WHERE actual IS DISTINCT FROM expected)            AS failed
  FROM v_checks;
