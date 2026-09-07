# Smart CNC Factory MES Copilot

Prototype industrial AI agent for a virtual CNC factory:

**Natural language → AI agent → controlled MES tools → deterministic calculation → validated, explainable answer.**

> The LLM understands the question, plans the steps and explains the result.
> It never touches the database and never produces a number.

## Status — Day 1 of 10 complete

| Day | Deliverable | Status |
|-----|-------------|--------|
| 1 | Requirements finalised · architecture · DB schema · demo questions | ✅ done |
| 2 | Virtual MES seed data (`db/seed.sql`) | next |
| 3 | MES tools / FastAPI endpoints | |
| 4 | Agent: domain guard, rewriting, intent extraction, tool selection | |
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

## Getting started (database)

```bash
cp .env.example .env
docker compose up -d postgres          # schema.sql runs automatically on first start
docker compose exec postgres psql -U mes -d mes -c '\dt'
```

Re-applying the schema to a running database:

```bash
docker compose exec -T postgres psql -U mes -d mes < db/schema.sql
```

`db/schema.sql` is idempotent and verified against PostgreSQL 16 (9 tables + seeded rule thresholds).
