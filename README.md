# Smart CNC Factory MES Copilot

Prototype industrial AI agent for a virtual CNC factory:

**Natural language → AI agent → controlled MES tools → deterministic calculation → validated, explainable answer.**

> The LLM understands the question, plans the steps and explains the result.
> It never touches the database and never produces a number.

## Status — Day 3 of 10 complete

| Day | Deliverable | Status |
|-----|-------------|--------|
| 1 | Requirements finalised · architecture · DB schema · demo questions | ✅ done |
| 2 | Virtual MES seed data + 20 data assertions | ✅ done |
| 3 | MES tool layer + FastAPI + 62 tests | ✅ done |
| 4 | Agent: domain guard, rewriting, intent extraction, tool selection | next |
| 5 | Multi-step planning + execution | |
| 6 | Capacity calculation + rule engine | |
| 7 | Missing data, domain restriction, validation, explanation | |
| 8 | Next.js frontend | |
| 9 | Scenario testing (`docs/04-demo-scenarios.md`) | |
| 10 | Final demo package | |

## Documentation

| Doc | Contents |
|-----|----------|
| [docs/01-requirements.md](docs/01-requirements.md) | Finalised functional/non-functional requirements, scope, acceptance criteria, Day-1 decisions |
| [docs/02-architecture.md](docs/02-architecture.md) | System diagram, request lifecycle, components, ADRs, capacity algorithm spec, API surface |
| [docs/03-database-schema.md](docs/03-database-schema.md) | ER model, table-by-table rationale, deviations from the requirement, seed-data plan |
| [docs/04-demo-scenarios.md](docs/04-demo-scenarios.md) | The 5 scenarios + reliability cases, expected tool sequences, pass criteria, demo order |
| [docs/05-seed-data.md](docs/05-seed-data.md) | The virtual factory dataset: what every value is for, verified numbers, known limits |
| [docs/06-mes-tools.md](docs/06-mes-tools.md) | The 8 controlled tools: envelope contract, time windows, security posture, HTTP surface |

## The five demo scenarios

1. **Capacity (hero)** — *How many A12 parts can we produce this week?*
2. **Machine health** — *Can CNC-03 continue production today?*
3. **Bottleneck** — *Which CNC machine is limiting A12 production?*
4. **Analysis** — *Why was A12 production lower yesterday?*
5. **Maintenance** — *Which machine needs maintenance attention?*

Plus reliability: request rewriting, clarification, missing-data refusal, out-of-domain rejection.

## Stack

Next.js + React + Tailwind · FastAPI (Python 3.12) · LangGraph + Pydantic · PostgreSQL 16 · Docker Compose.
The LLM provider is abstracted so the prototype can run against a local open-weight model for the future on-premises deployment.

## Getting started

```bash
make env          # copy .env.example to .env (factory timezone is Asia/Tokyo)
make up           # postgres + backend → http://localhost:8000/docs
make test         # 62 backend tests
make db-verify    # 20 data assertions over the seeded factory
```

Ask the factory a question through the controlled tool layer:

```bash
curl -s localhost:8000/api/tools                     # the 8 tools the model may call
curl -s -X POST localhost:8000/api/tools/get_available_machines \
     -H 'content-type: application/json' \
     -d '{"machine_type":"CNC_LATHE","time_window":"this_week"}'
```

### Database tasks

| Command | Purpose |
|---------|---------|
| `make db-seed` | rebase the factory onto the current ISO week (idempotent) |
| `make db-verify` | run the 20 data assertions — expected vs actual vs PASS/FAIL |
| `make db-rehearse DATE=2026-09-11` | seed and verify as if today were that date, to rehearse a demo |
| `make db-reset` | destroy the volume and rebuild from scratch |
| `make db-shell` | open psql |

### How the layers hold together

The database is seeded deterministically and verified by 20 SQL assertions; the
tool layer is verified by 62 Python tests that reach the same numbers through a
completely different path. `db/verify.sql` stays the independent oracle for the
Day-6 calculation engine.

The dataset is deterministic and date-relative: every date derives from the current ISO week, so the
demo tells the same story whenever it is shown. `db/verify.sql` recomputes capacity, bottleneck,
machine health and plan-vs-actual in plain SQL as an independent oracle for the Day-6 engine —
**20/20 assertions pass Monday through Friday** (see [docs/05-seed-data.md](docs/05-seed-data.md) for
the weekend limitation).
