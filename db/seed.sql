-- =====================================================================
-- Smart CNC Factory MES Copilot — virtual factory seed data
-- PostgreSQL 16 · Day 2 deliverable
--
-- Design rules
--   1. DETERMINISTIC. No random(). Every value is a fixed literal or a
--      pure function of the date, so the same dataset regenerates
--      identically and unit tests can assert exact integers.
--   2. DATE-RELATIVE. All dates derive from the current ISO week, so the
--      demo tells the same story whenever it is shown. Re-running this
--      file rebases the whole factory onto the current week.
--   3. IDEMPOTENT. Truncate-then-insert; safe to run repeatedly.
--   4. SCENARIO-DRIVEN. Every value exists to make one of the cases in
--      docs/04-demo-scenarios.md land. See docs/05-seed-data.md.
--
-- Runs automatically after schema.sql via docker-entrypoint-initdb.d
-- (alphabetical order), or manually:  make db-seed
-- =====================================================================

-- Factory-local time. Day-1 decision: "this week" is the current ISO week in
-- FACTORY-LOCAL time, not the database server's UTC. Without this, a factory
-- east of UTC gets the wrong "today" for several hours every night.
-- Override with:  psql -v factory_tz=Europe/Berlin -f db/seed.sql
\if :{?factory_tz}
\else
\set factory_tz 'Asia/Tokyo'
\endif

-- Rehearsal hook: seed the factory as if today were some other date, to
-- confirm the demo story holds on the day it will actually be shown.
--   psql -v demo_today="DATE '2026-09-11'" -f db/seed.sql
\if :{?demo_today}
\else
\set demo_today 'CURRENT_DATE'
\endif

-- Persist it for every future session (backend, psql, tools).
SELECT format('ALTER DATABASE %I SET timezone TO %L', current_database(), :'factory_tz')
\gexec

BEGIN;

SET LOCAL timezone TO :'factory_tz';

TRUNCATE TABLE production_history,
               machine_shift_calendar,
               maintenance,
               production_orders,
               parts,
               inventory,
               machines
    RESTART IDENTITY CASCADE;

-- ---------------------------------------------------------------------
-- Seed context — every date in this file is derived from these values.
-- last_production_day = most recent working day strictly before today
--   (Mon–Sat are working days; Sunday is not). This is what the
--   "yesterday" scenario resolves to.
-- ---------------------------------------------------------------------
CREATE TEMP TABLE seed_ctx ON COMMIT DROP AS
SELECT
    date_trunc('week', (:demo_today)::date)::date         AS week_start,   -- Monday
    (date_trunc('week', (:demo_today)::date)::date + 6)   AS week_end,     -- Sunday
    (:demo_today)::date                                   AS today,
    (SELECT max(d)::date
       FROM generate_series((:demo_today)::date - 7, (:demo_today)::date - 1, interval '1 day') d
      WHERE EXTRACT(ISODOW FROM d) <= 6)                  AS last_production_day;

-- =====================================================================
-- 1. MACHINES
-- =====================================================================
-- Lathes  CNC-01..03  -> A12 Bearing, B20 Shaft
-- Mills   CNC-04..05  -> C15 Housing
--
-- Sensor snapshot is chosen so that:
--   S2  CNC-03 is healthy today (52 °C / 1.8 mm/s) and can keep running.
--   S5  CNC-04 breaches vibration (3.1 vs 2.5 mm/s, +24 %) and
--       CNC-01 breaches temperature (72.5 vs 70 °C, +3.6 %).
--       Both have exactly one breach, so the tie-break on relative
--       severity is exercised and must select CNC-04.
--   S5  CNC-02 has a NULL vibration reading (sensor offline) and must be
--       reported "not assessable", never "healthy".
--   No machine breaches the 90 % utilisation threshold: utilisation is
--   bottleneck context, not a health verdict.
-- =====================================================================
INSERT INTO machines
    (machine_id, machine_name, machine_type, status, current_job,
     available_hours, temperature_c, vibration_mm_s, utilization_pct, last_reading_at) VALUES
    ('CNC-01', 'CNC Lathe 01',   'CNC_LATHE', 'running', NULL, NULL, 72.50, 1.20, 84.20, now()),
    ('CNC-02', 'CNC Lathe 02',   'CNC_LATHE', 'running', NULL, NULL, 61.00, NULL, 79.60, now()),
    ('CNC-03', 'CNC Lathe 03',   'CNC_LATHE', 'running', NULL, NULL, 52.00, 1.80, 46.30, now()),
    ('CNC-04', 'CNC Milling 04', 'CNC_MILL',  'idle',    NULL, NULL, 66.50, 3.10, 31.80, now()),
    ('CNC-05', 'CNC Milling 05', 'CNC_MILL',  'running', NULL, NULL, 64.20, 2.00, 88.10, now());

-- =====================================================================
-- 2. INVENTORY
-- =====================================================================
-- STEEL-4140 is deliberately plentiful: the hero scenario (A12) must be
--   machine-constrained, not material-constrained.
-- ALU-6061 is deliberately short — below its own reorder level, and below
--   the 220 pcs still open on PO-3001: C15 stays material-constrained on
--   every weekday, which exercises the min(machine, material) branch of
--   the capacity engine and the "material is the bottleneck" answer.
-- STEEL-1045 has a NULL quantity (stock count in progress) -> any
--   question about it must return "unknown", never zero.
-- =====================================================================
INSERT INTO inventory (material_id, material_name, unit, available_quantity, reorder_level) VALUES
    ('STEEL-4140', 'Steel 4140 round bar blank', 'pcs', 9600.00, 2000.00),
    ('ALU-6061',   'Aluminium 6061 billet',      'pcs',  180.00,  200.00),
    ('BRZ-C932',   'Bronze C932 bushing blank',  'pcs', 1500.00,  300.00),
    ('STEEL-1045', 'Steel 1045 round bar',       'pcs',    NULL,  500.00);

-- =====================================================================
-- 3. PARTS
-- =====================================================================
-- B20 has NO cycle time on purpose (FR-8 / scenario R3): it is a newly
-- introduced part whose routing has not been time-studied yet. The agent
-- must refuse to calculate its capacity and name the missing field
-- instead of substituting A12's cycle time or an average.
-- =====================================================================
INSERT INTO parts
    (part_id, part_name, material_id, material_qty_per_unit, cycle_time_min,
     required_machine_type, standard_reject_pct) VALUES
    ('A12', 'A12 Bearing', 'STEEL-4140', 1.000,  3.500, 'CNC_LATHE', 2.00),
    ('B20', 'B20 Shaft',   'STEEL-4140', 1.200,   NULL, 'CNC_LATHE', NULL),
    ('C15', 'C15 Housing', 'ALU-6061',   1.000, 12.000, 'CNC_MILL',  1.50);

COMMENT ON TABLE parts IS
    'B20.cycle_time_min is intentionally NULL — new part, routing not yet time-studied (scenario R3).';

-- =====================================================================
-- 4. PRODUCTION ORDERS
-- =====================================================================
INSERT INTO production_orders
    (order_id, part_id, planned_quantity, completed_quantity, due_date, status)
SELECT * FROM (
    SELECT 'PO-1000', 'A12', 1200, 1200, c.week_start -  3, 'completed'::order_status_t   FROM seed_ctx c
    UNION ALL SELECT 'PO-1001', 'A12', 1500, 1500, c.week_start -  1, 'completed'         FROM seed_ctx c
    UNION ALL SELECT 'PO-1002', 'A12', 1200,  640, c.week_start +  4, 'in_progress'       FROM seed_ctx c
    UNION ALL SELECT 'PO-1003', 'A12',  900,    0, c.week_start + 11, 'released'          FROM seed_ctx c
    UNION ALL SELECT 'PO-1004', 'A12',  600,    0, c.week_start + 18, 'planned'           FROM seed_ctx c
    UNION ALL SELECT 'PO-2001', 'B20',  300,    0, c.week_start + 11, 'planned'           FROM seed_ctx c
    UNION ALL SELECT 'PO-3001', 'C15',  400,  180, c.week_start +  5, 'in_progress'       FROM seed_ctx c
    UNION ALL SELECT 'PO-3002', 'C15',  250,    0, c.week_start + 12, 'released'          FROM seed_ctx c
    UNION ALL SELECT 'PO-3003', 'C15',  300,  300, c.week_start -  2, 'completed'         FROM seed_ctx c
    UNION ALL SELECT 'PO-3004', 'C15',  150,    0, c.week_start +  9, 'cancelled'         FROM seed_ctx c
) o;

UPDATE machines SET current_job = 'PO-1002' WHERE machine_id IN ('CNC-01', 'CNC-02');
UPDATE machines SET current_job = 'PO-1003' WHERE machine_id  = 'CNC-03';
UPDATE machines SET current_job = 'PO-3001' WHERE machine_id  = 'CNC-05';
-- CNC-04 is idle: current_job stays NULL.

-- =====================================================================
-- 5. SHIFT CALENDAR  (source of truth for availability — ADR-7)
-- =====================================================================
-- Two 8 h shifts Mon–Fri, one 8 h shift Sat, no production Sun.
-- Three weeks back and two weeks forward, so "yesterday", "this week"
-- and "next week" are all answerable.
-- =====================================================================
INSERT INTO machine_shift_calendar (machine_id, shift_date, planned_hours, shift_label)
SELECT m.machine_id,
       d::date,
       CASE WHEN EXTRACT(ISODOW FROM d) = 7 THEN 0.00
            WHEN EXTRACT(ISODOW FROM d) = 6 THEN 8.00
            ELSE 16.00 END,
       CASE WHEN EXTRACT(ISODOW FROM d) = 7 THEN 'off'
            WHEN EXTRACT(ISODOW FROM d) = 6 THEN 'A'
            ELSE 'A+B' END
  FROM machines m
 CROSS JOIN seed_ctx c
 CROSS JOIN LATERAL generate_series(c.week_start - 21, c.week_start + 13, interval '1 day') d;

-- =====================================================================
-- 6. MAINTENANCE
-- =====================================================================
-- CNC-03 spindle bearing overhaul: a 5.5 h block on every remaining
-- working day of the current week, starting TOMORROW. Two consequences,
-- both required by the demo script:
--   · nothing is active on CNC-03 today  -> S2 answers "can continue";
--   · CNC-03 always has the lowest effective hours in the remaining
--     window -> S1/S3 name it as the bottleneck on any weekday the demo
--     is run, instead of only on the day the data was authored.
-- =====================================================================
INSERT INTO maintenance
    (machine_id, maintenance_date, duration_hours, maintenance_type, maintenance_status, description)
SELECT 'CNC-03', d::date, 5.50, 'preventive', 'scheduled',
       'Spindle bearing overhaul - staged daily block'
  FROM seed_ctx c
 CROSS JOIN LATERAL generate_series(c.today + 1, c.week_start + 5, interval '1 day') d
 WHERE EXTRACT(ISODOW FROM d) <= 6;

-- Unplanned stop behind the S4 shortfall: the same 2.1 h that appears as
-- production_history.downtime_hours, so the cause is corroborated by a
-- second table instead of being asserted by the LLM.
INSERT INTO maintenance
    (machine_id, maintenance_date, duration_hours, maintenance_type, maintenance_status, description)
SELECT 'CNC-02', c.last_production_day, 2.10, 'corrective', 'completed',
       'Tool changer fault - unplanned stop' FROM seed_ctx c;

-- Routine work outside the current week (must NOT affect this week's capacity).
INSERT INTO maintenance
    (machine_id, maintenance_date, duration_hours, maintenance_type, maintenance_status, description)
SELECT 'CNC-04', c.week_start +  8, 3.00, 'inspection'::maintenance_type_t, 'scheduled'::maintenance_status_t, 'Vibration follow-up inspection' FROM seed_ctx c
UNION ALL
SELECT 'CNC-01', c.week_start +  9, 4.00, 'preventive', 'scheduled', 'Coolant system service'         FROM seed_ctx c
UNION ALL
SELECT 'CNC-05', c.week_start + 10, 6.00, 'preventive', 'scheduled', 'Ball screw replacement'         FROM seed_ctx c
UNION ALL
SELECT 'CNC-01', c.week_start -  4, 3.50, 'preventive', 'completed', 'Coolant system service'         FROM seed_ctx c;

-- =====================================================================
-- 7. PRODUCTION HISTORY
-- =====================================================================
-- Three weeks of daily records on working days only, for the part each
-- machine actually runs. Variance is a pure function of the day-of-year
-- and the machine number — no random() — so the dataset is reproducible.
-- =====================================================================
WITH allocation (machine_id, part_id, weekday_plan) AS (
    VALUES ('CNC-01', 'A12', 100),
           ('CNC-02', 'A12', 100),
           ('CNC-03', 'A12',  50),
           ('CNC-04', 'C15',  60),
           ('CNC-05', 'C15',  60)
),
day AS (
    SELECT s.shift_date,
           s.machine_id,
           s.planned_hours,
           EXTRACT(DOY FROM s.shift_date)::int              AS doy,
           substring(s.machine_id from 5)::int              AS mach_no
      FROM machine_shift_calendar s
     CROSS JOIN seed_ctx c
     WHERE s.planned_hours > 0
       AND s.shift_date BETWEEN c.week_start - 21 AND c.last_production_day
),
calc AS (
    SELECT d.machine_id,
           a.part_id,
           d.shift_date,
           CASE WHEN d.planned_hours >= 16 THEN a.weekday_plan ELSE a.weekday_plan / 2 END AS plan,
           ((d.doy * 13 + d.mach_no * 7) % 11) - 5                                         AS variance,
           CASE WHEN a.part_id = 'A12' THEN 2 + (d.doy % 3) ELSE 1 + (d.doy % 2) END       AS rejects,
           CASE WHEN (d.doy + d.mach_no) % 9 = 0 THEN 1.20 ELSE 0.00 END                   AS downtime
      FROM day d
      JOIN allocation a ON a.machine_id = d.machine_id
)
INSERT INTO production_history
    (machine_id, part_id, production_date, planned_quantity,
     produced_quantity, rejected_quantity, downtime_hours, downtime_reason)
SELECT machine_id,
       part_id,
       shift_date,
       plan,
       greatest(0, plan + variance - CASE WHEN downtime > 0 THEN 20 ELSE 0 END),
       rejects,
       downtime,
       CASE WHEN downtime > 0 THEN 'Tool change / setup overrun' END
  FROM calc;

-- ---------------------------------------------------------------------
-- S4 incident — overwrite the last production day for A12.
--
--   planned 250 · produced 215  -> shortfall 35 = exactly 14.0 % below plan
--   CNC-02 lost 2.1 h; at a 3.5 min cycle that is 36 parts, which
--     accounts for essentially the whole shortfall -> primary cause
--   8 rejects out of 223 processed = 3.6 % -> secondary factor
--   CNC-03 over-produced by 4, partially offsetting the loss
-- The engine derives all of these; none of them is a stored percentage.
-- ---------------------------------------------------------------------
INSERT INTO production_history
    (machine_id, part_id, production_date, planned_quantity,
     produced_quantity, rejected_quantity, downtime_hours, downtime_reason)
SELECT 'CNC-01', 'A12', c.last_production_day, 100, 97, 3, 0.00, NULL::text                            FROM seed_ctx c
UNION ALL
SELECT 'CNC-02', 'A12', c.last_production_day, 100, 64, 3, 2.10, 'Tool changer fault - unplanned stop' FROM seed_ctx c
UNION ALL
SELECT 'CNC-03', 'A12', c.last_production_day,  50, 54, 2, 0.00, NULL                                  FROM seed_ctx c
ON CONFLICT (machine_id, part_id, production_date) DO UPDATE
   SET planned_quantity  = EXCLUDED.planned_quantity,
       produced_quantity = EXCLUDED.produced_quantity,
       rejected_quantity = EXCLUDED.rejected_quantity,
       downtime_hours    = EXCLUDED.downtime_hours,
       downtime_reason   = EXCLUDED.downtime_reason;

-- =====================================================================
-- 8. DISPLAY FIELD — machines.available_hours
-- =====================================================================
-- Derived, never authoritative (ADR-7): remaining planned hours from
-- today to Sunday, minus maintenance still scheduled in that window.
-- The capacity engine recomputes this from the calendar; this column
-- exists only so the UI status strip has a number to show.
-- =====================================================================
UPDATE machines m
   SET available_hours = GREATEST(
        0,
        COALESCE((SELECT SUM(s.planned_hours)
                    FROM machine_shift_calendar s
                   WHERE s.machine_id = m.machine_id
                     AND s.shift_date BETWEEN (SELECT today    FROM seed_ctx)
                                          AND (SELECT week_end FROM seed_ctx)), 0)
      - COALESCE((SELECT SUM(mt.duration_hours)
                    FROM maintenance mt
                   WHERE mt.machine_id = m.machine_id
                     AND mt.maintenance_date BETWEEN (SELECT today    FROM seed_ctx)
                                                 AND (SELECT week_end FROM seed_ctx)
                     AND mt.maintenance_status IN ('scheduled', 'in_progress')), 0));

COMMIT;
