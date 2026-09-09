# 06 — The MES Tool Layer (Day 3)

Code: [`backend/app/tools/`](../backend/app/tools) · [`backend/app/repositories/`](../backend/app/repositories) · [`backend/app/api/routes.py`](../backend/app/api/routes.py)
Tests: [`backend/tests/`](../backend/tests) — 62 passing.

The layer that stands between the language model and the factory. The model
chooses **which** tool to call; it never sees a table, never writes SQL, and
never produces a number.

## 1. The contract

Every tool returns the same envelope (FR-5), whatever it was asked:

```jsonc
{
  "tool": "get_part_information",
  "ok": true,
  "data":   { /* typed payload, one shape per tool */ },
  "window": { "label": "this_week", "start": "2026-09-08", "end": "2026-09-13",
              "days": 6, "timezone": "Asia/Tokyo", "basis": "…why these dates…" },
  "sources": [ { "table": "parts", "fields": ["cycle_time_min"], "keys": ["A12"], "rows": 1 } ],
  "missing_fields": [ { "entity": "B20", "field": "parts.cycle_time_min", "reason": "…" } ],
  "not_found": [],
  "warnings": [],
  "elapsed_ms": 3
}
```

Three fields go beyond the FR-5 minimum, each paying for itself:

| Field | Why |
|-------|-----|
| `not_found` | Scenario R5 must answer *"CNC-09 does not exist"*. Structured data beats making the model parse a warning string, and the response carries the real ids alongside it. |
| `window` | An answer that says "this week" must be able to say **which dates** — and `basis` explains the elapsed-day rule in plain language. |
| `tool` / `ok` / `elapsed_ms` | Trace metadata for the audit log and the "AI Analysis Steps" panel. |

## 2. Three habits every tool keeps

**Facts, not verdicts.** `get_machine_status` returns 3.1 mm/s *and* the 2.5 mm/s
threshold. It does not conclude "unhealthy". Ratios, capacities and rankings are
the Day-6 engine's job, in deterministic Python. That separation is what makes
acceptance criterion 4 checkable rather than merely claimed — a test asserts
`ProductionTotals` carries no reject-rate field.

**NULL is reported, never smoothed.** A missing cycle time becomes a
`missing_fields` entry naming `parts.cycle_time_min` with a reason a factory
manager can read. That is the mechanism behind FR-8: the agent refuses because a
tool told it something is unknown, not because a prompt asked it to be careful.
Uncounted stock is `null` with `below_reorder_level: null` — unknown, not zero.

**Everything is sourced.** Each result lists the tables, columns and entity ids
it read. The "Data Used" panel is assembled from these, not written by the model.

## 3. The eight tools

| Tool | Parameters | Returns | Scenarios |
|------|-----------|---------|-----------|
| `get_machine_status` | `machine_id?` | machines + `rule_thresholds` + `known_machine_ids` when one is missing | S2, S5, Demo 1 |
| `get_available_machines` | `machine_type?`, `time_window` | per machine: planned / maintenance / effective hours, eligibility | S1, S3 |
| `get_part_information` | `part_id` | cycle time, material and quantity per part, required machine type | S1, S3, R3 |
| `get_production_orders` | `part_id?`, `status?`, `time_window?` | orders with remaining quantity + totals | S1, S4 |
| `get_material_inventory` | `material_id?` | stock, reorder level, below-reorder flag | S1 |
| `get_maintenance_schedule` | `machine_id?`, `time_window`, `include_completed` | events, hours per machine, machines under maintenance **today** | S1–S5 |
| `get_production_history` | `part_id?`, `machine_id?`, `time_window` | daily rows, raw totals, totals per machine, last production day | S4 |
| `calculate_production_capacity` | `part_id`, `time_window` | **Day 6** — declared, not yet built | S1, S3 |

Two details are load-bearing:

- **Thresholds ride along with machine status.** S2 and S5 must name the limit a
  reading was compared against, and FR-5 fixes the tool count at eight — so
  `rule_thresholds` is returned as reference data rather than becoming a ninth tool.
- **`machines_under_maintenance_today` ignores the requested window.** "Can CNC-03
  run right now?" must not change its answer because the caller happened to ask
  about next week.

### The eighth tool

`calculate_production_capacity` is registered as **declared but not implemented**,
with `planned_for: "Day 6 — calculation and rule engine"`. Calling it returns
`501` naming the day it arrives. Leaving it out of the registry would have been
the quieter option, but the registry is the contract: all eight tools are visible,
and an early call fails loudly and specifically instead of looking like a typo.

## 4. Time windows

Resolved in [`app/timewindow.py`](../backend/app/timewindow.py) — in Python, not
SQL, so the rule is unit-testable and every result can report the dates it used.

| Label | Meaning |
|-------|---------|
| `today` · `tomorrow` · `yesterday` | single days |
| `this_week` | **remaining** part of the current ISO week, today → Sunday |
| `full_week` | the whole ISO week, Monday → Sunday |
| `next_week` · `last_week` | complete ISO weeks |
| `last_7_days` · `last_30_days` | rolling windows ending yesterday |
| `2026-09-11` · `2026-09-08..2026-09-13` | explicit date or range |

`this_week` carries the Day-1 decision: a manager asking "how many can we produce
this week" means the hours still ahead. Asked on Thursday, Monday's shifts are not
capacity. The unresolvable-window path returns `422` listing what is supported,
rather than silently defaulting to something plausible.

All of it is factory-local (`Asia/Tokyo`), never the server's UTC — the failure
mode that fix prevents is a demo running a full day behind for nine hours out of
every twenty-four.

## 5. Security posture

| Control | Implementation |
|---------|----------------|
| No arbitrary table access | The model may call eight names; anything else raises `UnknownToolError` → `404`. |
| No dynamic SQL | Every statement is fixed and parameterised in the repository layer. Nothing is assembled from model output (ADR-2). |
| Read-only connection | Tools connect as `mes_ro`: SELECT grants only, plus `default_transaction_read_only`. |
| Verified, not assumed | `tests/test_readonly.py` asserts DELETE, UPDATE, INSERT and DROP are all refused on the live connection. |

`db/schema.sql` now creates and grants that role, idempotently. This tightens
ADR-6: the earlier sketch gave `mes_ro` INSERT on `agent_run_log`, but the audit
trail is written over the application's own read-write connection (delivered
Day 5), which leaves the tool path with no write capability at all.

## 6. HTTP surface

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/health` | liveness, factory clock, DB user, read-only flag, tool counts |
| `GET` | `/api/machines` | factory status strip for the dashboard |
| `GET` | `/api/tools` | the catalogue: every tool, its JSON schema, and the window vocabulary |
| `GET` | `/api/tools/{name}` | one tool's contract |
| `POST` | `/api/tools/{name}` | invoke a tool with JSON parameters |
| `GET` | `/docs` | OpenAPI UI |

`GET /api/tools` emits each tool's schema generated **from the same Pydantic model
the tool validates against**, in the shape LLM function calling expects — so the
Day-4 agent describes tools to the model from the single source of truth, and the
description cannot drift from the behaviour.

Exposing the tools over HTTP as well as in-process is deliberate: in the demo you
can show the factory manager the exact call and the exact JSON behind a number.

Error codes are specific on purpose: `404` unknown tool, `422` bad parameters or
an unresolvable window, `501` declared-but-not-built.

## 7. Verified against the seeded factory

Live output from `POST /api/tools/get_available_machines` with
`{"machine_type": "CNC_LATHE", "time_window": "this_week"}` on 2026-09-08:

```
window 2026-09-08 -> 2026-09-13 (6d, Asia/Tokyo)
  CNC-01  planned=72.00  maint= 0.00  effective=72.00  eligible=True
  CNC-02  planned=72.00  maint= 0.00  effective=72.00  eligible=True
  CNC-03  planned=72.00  maint=22.00  effective=50.00  eligible=True
  total effective hours = 194.0   sources=[machine_shift_calendar, maintenance, machines]
```

These are the same numbers `db/verify.sql` produces independently in SQL, reached
through a completely different path. The S4 incident reads back through the tool
as planned 250 / produced 215 / rejected 8 / downtime 2.1 h — matching
[`05-seed-data.md`](05-seed-data.md) exactly.

### Test suite (62 tests)

| File | Covers |
|------|--------|
| `test_timewindow.py` | 17 pure tests: the elapsed-day rule, week boundaries, every keyword, explicit ranges, rejected input |
| `test_tools.py` | 27 tests against the seeded factory: every tool, unknown entities, missing fields, eligibility, the S4 numbers |
| `test_api.py` | 12 tests over real HTTP through the ASGI app, including the 404/422/501 paths |
| `test_readonly.py` | 6 tests proving the tool connection cannot write |

## 8. Running it

```bash
make up                # postgres + backend on http://localhost:8000/docs
make test              # 62 tests
make lint              # ruff check + format check
make backend-dev       # local uvicorn with reload
```

## 9. What Day 4 picks up

The tools are complete and callable; the agent is not written yet. Day 4 adds the
domain guard, request rewriting, structured intent extraction and tool selection
on top of `registry.schemas()`. Nothing in this layer should need to change for
it — that is the point of making the tools the contract.
