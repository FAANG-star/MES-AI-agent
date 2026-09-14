-- =====================================================================
-- Smart CNC Factory MES Copilot — Virtual MES schema
-- PostgreSQL 16 · the virtual MES schema
-- Seed data lives in db/seed.sql.
-- =====================================================================

BEGIN;

DROP TABLE IF EXISTS production_history      CASCADE;
DROP TABLE IF EXISTS maintenance             CASCADE;
DROP TABLE IF EXISTS machine_shift_calendar  CASCADE;
DROP TABLE IF EXISTS production_orders       CASCADE;
DROP TABLE IF EXISTS parts                   CASCADE;
DROP TABLE IF EXISTS inventory               CASCADE;
DROP TABLE IF EXISTS machines                CASCADE;
DROP TABLE IF EXISTS rule_thresholds         CASCADE;
DROP TABLE IF EXISTS agent_run_log           CASCADE;

DROP TYPE IF EXISTS machine_status_t     CASCADE;
DROP TYPE IF EXISTS order_status_t       CASCADE;
DROP TYPE IF EXISTS maintenance_status_t CASCADE;
DROP TYPE IF EXISTS maintenance_type_t   CASCADE;

CREATE TYPE machine_status_t     AS ENUM ('running', 'idle', 'maintenance', 'down');
CREATE TYPE order_status_t       AS ENUM ('planned', 'released', 'in_progress', 'completed', 'cancelled');
CREATE TYPE maintenance_status_t AS ENUM ('scheduled', 'in_progress', 'completed', 'cancelled');
CREATE TYPE maintenance_type_t   AS ENUM ('preventive', 'corrective', 'inspection');

-- ---------------------------------------------------------------------
-- machines — one row per CNC machine (CNC-01 .. CNC-05)
-- ---------------------------------------------------------------------
CREATE TABLE machines (
    machine_id      TEXT PRIMARY KEY,                 -- 'CNC-03'
    machine_name    TEXT            NOT NULL,
    machine_type    TEXT            NOT NULL,         -- 'CNC_LATHE' | 'CNC_MILL' — matched against parts.required_machine_type
    status          machine_status_t NOT NULL DEFAULT 'idle',
    current_job     TEXT,                             -- order_id currently loaded, NULL if none
    available_hours NUMERIC(6,2) CHECK (available_hours >= 0),  -- DISPLAY ONLY (see ADR-7); capacity math uses machine_shift_calendar
    temperature_c   NUMERIC(5,2),                     -- NULL = sensor unavailable (missing-data demo)
    vibration_mm_s  NUMERIC(5,2),
    utilization_pct NUMERIC(5,2) CHECK (utilization_pct BETWEEN 0 AND 100),
    last_reading_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON COLUMN machines.available_hours IS
    'Denormalised remaining hours in the current ISO week. UI display only — never used by calculate_production_capacity.';

-- ---------------------------------------------------------------------
-- inventory — raw material stock
-- ---------------------------------------------------------------------
CREATE TABLE inventory (
    material_id        TEXT PRIMARY KEY,              -- 'STEEL-4140'
    material_name      TEXT NOT NULL,
    unit               TEXT NOT NULL DEFAULT 'pcs',   -- 'pcs' | 'kg' | 'bar'
    available_quantity NUMERIC(12,2) CHECK (available_quantity >= 0),  -- NULL = unknown stock
    reorder_level      NUMERIC(12,2),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- parts — manufactured parts (A12 Bearing, B20 Shaft, C15 Housing)
-- ---------------------------------------------------------------------
CREATE TABLE parts (
    part_id               TEXT PRIMARY KEY,           -- 'A12'
    part_name             TEXT NOT NULL,              -- 'A12 Bearing'
    material_id           TEXT REFERENCES inventory (material_id),
    material_qty_per_unit NUMERIC(10,3) CHECK (material_qty_per_unit > 0),  -- material consumed per finished part
    cycle_time_min        NUMERIC(8,3) CHECK (cycle_time_min > 0),          -- NULL ON PURPOSE for B20 → missing-data scenario
    required_machine_type TEXT NOT NULL,
    standard_reject_pct   NUMERIC(5,2) CHECK (standard_reject_pct BETWEEN 0 AND 100),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON COLUMN parts.cycle_time_min IS
    'Minutes of machine time per finished part. NULL means unknown — tools must refuse to calculate capacity (FR-8).';

-- ---------------------------------------------------------------------
-- production_orders
-- ---------------------------------------------------------------------
CREATE TABLE production_orders (
    order_id           TEXT PRIMARY KEY,              -- 'PO-1042'
    part_id            TEXT NOT NULL REFERENCES parts (part_id),
    planned_quantity   INTEGER NOT NULL CHECK (planned_quantity > 0),
    completed_quantity INTEGER NOT NULL DEFAULT 0 CHECK (completed_quantity >= 0),
    due_date           DATE NOT NULL,
    status             order_status_t NOT NULL DEFAULT 'planned',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT completed_not_over_planned CHECK (completed_quantity <= planned_quantity)
);
CREATE INDEX idx_orders_part_due ON production_orders (part_id, due_date);
CREATE INDEX idx_orders_status   ON production_orders (status);

-- ---------------------------------------------------------------------
-- machine_shift_calendar — planned production hours per machine per day.
-- Source of truth for availability; makes 'today' / 'tomorrow' / 'this week'
-- answerable with one query (ADR-7).
-- ---------------------------------------------------------------------
CREATE TABLE machine_shift_calendar (
    machine_id    TEXT NOT NULL REFERENCES machines (machine_id) ON DELETE CASCADE,
    shift_date    DATE NOT NULL,
    planned_hours NUMERIC(5,2) NOT NULL CHECK (planned_hours >= 0 AND planned_hours <= 24),
    shift_label   TEXT,                                -- 'A' | 'B' | 'weekend'
    PRIMARY KEY (machine_id, shift_date)
);
CREATE INDEX idx_shift_date ON machine_shift_calendar (shift_date);

-- ---------------------------------------------------------------------
-- maintenance — planned/active downtime, subtracted from available hours
-- ---------------------------------------------------------------------
CREATE TABLE maintenance (
    maintenance_id     BIGSERIAL PRIMARY KEY,
    machine_id         TEXT NOT NULL REFERENCES machines (machine_id) ON DELETE CASCADE,
    maintenance_date   DATE NOT NULL,
    duration_hours     NUMERIC(5,2) NOT NULL CHECK (duration_hours >= 0),
    maintenance_type   maintenance_type_t   NOT NULL DEFAULT 'preventive',
    maintenance_status maintenance_status_t NOT NULL DEFAULT 'scheduled',
    description        TEXT
);
CREATE INDEX idx_maint_machine_date ON maintenance (machine_id, maintenance_date);
CREATE INDEX idx_maint_date_status  ON maintenance (maintenance_date, maintenance_status);

-- ---------------------------------------------------------------------
-- production_history — one row per machine × part × day (Scenario 4)
-- ---------------------------------------------------------------------
CREATE TABLE production_history (
    history_id        BIGSERIAL PRIMARY KEY,
    machine_id        TEXT NOT NULL REFERENCES machines (machine_id) ON DELETE CASCADE,
    part_id           TEXT NOT NULL REFERENCES parts (part_id)       ON DELETE CASCADE,
    production_date   DATE    NOT NULL,
    planned_quantity  INTEGER NOT NULL DEFAULT 0 CHECK (planned_quantity  >= 0),
    produced_quantity INTEGER NOT NULL DEFAULT 0 CHECK (produced_quantity >= 0),
    rejected_quantity INTEGER NOT NULL DEFAULT 0 CHECK (rejected_quantity >= 0),
    downtime_hours    NUMERIC(5,2) NOT NULL DEFAULT 0 CHECK (downtime_hours >= 0),
    downtime_reason   TEXT,
    UNIQUE (machine_id, part_id, production_date)
);
CREATE INDEX idx_hist_part_date ON production_history (part_id, production_date);
CREATE INDEX idx_hist_date      ON production_history (production_date);

-- ---------------------------------------------------------------------
-- rule_thresholds — machine-health limits, cited as a source (ADR-4)
-- ---------------------------------------------------------------------
CREATE TABLE rule_thresholds (
    rule_key          TEXT PRIMARY KEY,               -- 'machine.temperature_c'
    display_name      TEXT NOT NULL,
    unit              TEXT NOT NULL,
    warning_threshold NUMERIC(10,3),
    critical_threshold NUMERIC(10,3),
    comparison        TEXT NOT NULL DEFAULT 'gte' CHECK (comparison IN ('gte', 'lte')),
    notes             TEXT
);

INSERT INTO rule_thresholds
    (rule_key, display_name, unit, warning_threshold, critical_threshold, comparison, notes) VALUES
    ('machine.temperature_c', 'Spindle temperature', '°C',   70,  85,  'gte', 'Warning at 70 °C, stop recommended at 85 °C'),
    ('machine.vibration_mm_s','Spindle vibration',   'mm/s', 2.5, 4.0, 'gte', 'Warning at 2.5 mm/s, stop recommended at 4.0 mm/s'),
    ('machine.utilization_pct','Utilisation',        '%',    90,  98,  'gte', 'Sustained high utilisation signals a bottleneck');

-- ---------------------------------------------------------------------
-- agent_run_log — audit trail: one row per question (explainability, demo)
-- ---------------------------------------------------------------------
CREATE TABLE agent_run_log (
    run_id         UUID PRIMARY KEY,
    asked_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    question       TEXT NOT NULL,
    rewritten      TEXT,
    intent         TEXT,
    entities       JSONB,
    plan           JSONB,
    tool_calls     JSONB,
    final_answer   TEXT,
    status         TEXT NOT NULL,      -- answered | clarify | refused_missing_data | rejected_out_of_domain | error
    grounded       BOOLEAN,
    latency_ms     INTEGER
);
CREATE INDEX idx_runlog_asked_at ON agent_run_log (asked_at DESC);

COMMIT;

-- ---------------------------------------------------------------------
-- Read-only role for the MES tool layer (ADR-6).
--
-- The 8 MES tools connect as mes_ro. Beyond SELECT-only grants, the role
-- carries default_transaction_read_only, so even a bug or a compromised
-- prompt cannot mutate factory data. The application's own connection
-- (DATABASE_URL) stays read-write and owns the agent_run_log audit trail.
--
-- Idempotent: creates the role only if missing, then resets its password.
--   psql -v ro_password=... -f db/schema.sql
-- ---------------------------------------------------------------------
\if :{?ro_password}
\else
\set ro_password 'mes_ro'
\endif

SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', 'mes_ro', :'ro_password')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mes_ro')
\gexec

SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L', 'mes_ro', :'ro_password')
\gexec

SELECT format('GRANT CONNECT ON DATABASE %I TO mes_ro', current_database())
\gexec

GRANT USAGE  ON SCHEMA public TO mes_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO mes_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO mes_ro;
ALTER ROLE mes_ro SET default_transaction_read_only = on;
