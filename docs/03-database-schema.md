# 03 — Virtual MES Database Schema

PostgreSQL 16. DDL: [`db/schema.sql`](../db/schema.sql). Seed data: [`db/seed.sql`](../db/seed.sql), documented in [`05-seed-data.md`](05-seed-data.md).

## 1. ER overview

```
                 inventory ─────────────┐
                (material_id)           │ material_id
                                        ▼
  machines ◀────── machine_shift_calendar        parts ──────▶ production_orders
 (machine_id)      (machine_id, shift_date)   (part_id)        (order_id)
      │  ▲                                        │
      │  └──── maintenance (machine_id, date)     │
      │                                           │
      └────────── production_history ─────────────┘
                  (machine_id, part_id, production_date)

  rule_thresholds  (standalone: health limits, cited as a data source)
  agent_run_log    (standalone: audit trail of every question)
```

## 2. Tables

| Table | Rows (target seed) | Purpose | Used by |
|-------|--------------------|---------|---------|
| `machines` | 5 | machine master + latest sensor snapshot | S2, S3, S5 |
| `parts` | 3 | part master: cycle time, material, required machine type | S1, S3 |
| `inventory` | 3–4 | raw-material stock | S1 |
| `production_orders` | ~10 | planned vs completed quantity, due dates | S1, S4 |
| `machine_shift_calendar` | 5 × 14 days | planned production hours per machine per day | S1, S3 |
| `maintenance` | ~8 | planned/active downtime | S1, S2, S3, S5 |
| `production_history` | ~90 | daily produced / rejected / downtime | S4 |
| `rule_thresholds` | 3 | health limits (seeded by the DDL itself) | S2, S5 |
| `agent_run_log` | grows | audit trail per question | demo / debug |

## 3. Departures from the requirement's table list — and why

| Requirement | Implemented as | Reason |
|-------------|----------------|--------|
| `Machines.available_hours` | kept, but **display only** | A single scalar cannot answer "today" and "this week" both. `machine_shift_calendar` is the source of truth for availability (ADR-7). The column stays because the requirement lists it and the status strip shows it. |
| `Parts.material` (text) | `material_id` FK → `inventory` **+** `material_qty_per_unit` | Material capacity = stock ÷ consumption per part. A free-text material name cannot be joined to stock, so the capacity calculation would be impossible. |
| `Maintenance` (no PK) | `maintenance_id BIGSERIAL` | A machine can have several maintenance entries on the same day. |
| `Production History` (produced, rejected) | **+** `planned_quantity`, `downtime_hours`, `downtime_reason` | Scenario 4 ("why was production lower yesterday?") needs plan-vs-actual and a downtime cause; without them the answer would have to be invented. |
| — | `rule_thresholds` (new) | Health limits become queryable, citable data instead of hard-coded prompt text (ADR-4). |
| — | `agent_run_log` (new) | Evidence for acceptance criteria 2, 5 and 7; also drives `GET /api/traces/{id}`. |

## 4. Field conventions

- **Cycle time** — `parts.cycle_time_min`, minutes per finished part. The unit is in the column name so it cannot be misread by a tool or a prompt.
- **Availability** — hours, `NUMERIC(5,2)`.
- **Sensors** — `temperature_c` (°C), `vibration_mm_s` (mm/s), `utilization_pct` (0–100).
- **Nullability is meaningful.** `cycle_time_min`, `material_qty_per_unit`, `available_quantity`, `temperature_c` and `vibration_mm_s` are nullable **on purpose**: NULL means *unknown*, and every tool must surface it in `missing_fields` so the agent refuses instead of estimating (FR-8).
- **Enums** for `status` fields — the LLM can only ever see valid values, and typos cannot enter the data.
- **CHECK constraints** encode the physics/business floor (no negative hours, completed ≤ planned, utilisation 0–100), so a bad seed script fails loudly when it is loaded rather than producing a wrong demo number.

## 5. Seed data

Implemented in [`db/seed.sql`](../db/seed.sql); the dataset, its rationale and the verified numbers
are documented in [`05-seed-data.md`](05-seed-data.md). Summary:

| Entity | Delivered |
|--------|-----------|
| Machines | 5 — CNC-01/02/03 lathes, CNC-04/05 mills. CNC-01 breaches the temperature limit, CNC-04 the vibration limit, CNC-02 has a NULL vibration reading, CNC-03 is healthy today |
| Parts | A12 (3.5 min, STEEL-4140) · B20 (**cycle time NULL** → refusal path) · C15 (12.0 min, ALU-6061) |
| Inventory | 4 materials; STEEL-4140 plentiful (A12 machine-bound), ALU-6061 short at 120 pcs (C15 material-bound every day), STEEL-1045 quantity NULL |
| Orders | 10, across all five statuses |
| Shift calendar | 175 rows — seven-day operation, 2 × 8 h a day, CNC-03 on one 8 h shift, 5 weeks of coverage |
| Maintenance | CNC-03 overhaul blocks on the remaining days of this week; a corrective record matching the S4 downtime yesterday; the rest outside this week |
| Production history | three weeks of daily records, plus the S4 incident yesterday |

Deviations from the initial plan (CNC-03 running rather than in maintenance, daily maintenance
blocks rather than one fixed block, and lower ALU-6061 stock) are explained in
[`05-seed-data.md §4`](05-seed-data.md).

## 6. Verification

`db/schema.sql` is idempotent (`DROP ... CASCADE` then `CREATE`) and has been applied cleanly to a PostgreSQL 16 instance; the `rule_thresholds` rows load with it.

```bash
make db-up        # first start applies schema.sql, seed.sql and verify.sql automatically
make db-verify    # 20 assertions over the seeded factory — 20/20 on every day of the week
```

`db/verify.sql` recomputes capacity, bottleneck, health ranking and plan-vs-actual in plain SQL as
an independent oracle for the Python calculation engine.
