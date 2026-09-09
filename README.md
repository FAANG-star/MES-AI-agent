# Smart CNC Factory MES Copilot

Prototype industrial AI agent for a virtual CNC factory:

**Natural language → AI agent → controlled MES tools → deterministic calculation → validated, explainable answer.**

> The LLM understands the question, plans the steps and explains the result.
> It never touches the database and never produces a number.
> It runs **locally**, so factory data never leaves the application environment.

## Status — Day 4 of 10 complete

| Day | Deliverable | Status |
|-----|-------------|--------|
| 1 | Requirements finalised · architecture · DB schema · demo questions | ✅ done |
| 2 | Virtual MES seed data + 20 data assertions | ✅ done |
| 3 | MES tool layer + FastAPI + 62 tests | ✅ done |
| 4 | Agent: domain guard, rewriting, intent extraction, tool selection | ✅ done |
| 5 | Multi-step planning + execution | next |
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
| [docs/07-agent-understanding.md](docs/07-agent-understanding.md) | Domain guard, request rewriting, typed intent, entity grounding, tool selection, LLM providers |

## The five demo scenarios

1. **Capacity (hero)** — *How many A12 parts can we produce this week?*
2. **Machine health** — *Can CNC-03 continue production today?*
3. **Bottleneck** — *Which CNC machine is limiting A12 production?*
4. **Analysis** — *Why was A12 production lower yesterday?*
5. **Maintenance** — *Which machine needs maintenance attention?*

Plus reliability: request rewriting, clarification, missing-data refusal, out-of-domain rejection.

## Stack

Next.js + React + Tailwind · FastAPI (Python 3.12) · LangGraph + Pydantic · PostgreSQL 16 · Docker Compose.

**The language model runs locally.** The prototype uses a locally deployed
open-weight model behind an OpenAI-compatible endpoint (Ollama / vLLM), so
factory questions and MES data stay inside the application environment — the
architecture the factory's isolated production network will need. The LLM
handles natural-language understanding and explanation; production calculations
and factory rules are executed by deterministic backend services.

## Getting started

```bash
make env          # copy .env.example to .env (factory timezone is Asia/Tokyo)
make up           # postgres + backend → http://localhost:8000/docs
make test         # 191 backend tests
make db-verify    # 20 data assertions over the seeded factory
```

Ask the factory a question through the controlled tool layer:

```bash
# What the agent understands, and how it plans to answer — nothing executes yet
curl -s -X POST localhost:8000/api/understand \
     -H 'content-type: application/json' \
     -d '{"question":"How many A12 can we produce this week?"}'

curl -s localhost:8000/api/tools                     # the 8 tools the model may call
curl -s -X POST localhost:8000/api/tools/get_available_machines \
     -H 'content-type: application/json' \
     -d '{"machine_type":"CNC_LATHE","time_window":"this_week"}'
```

### The language model (local)

`make up` starts the model server alongside the database and backend. Then:

```bash
make llm-pull LLM_MODEL=qwen2.5:7b-instruct   # download the model
make llm-check                                # is it reliable enough?
```

Measured against Ollama 0.33.3 on 4 CPU cores, no GPU: `qwen2.5:7b-instruct`
scored **21/21** on structured output, intent, entities and rewrites across the
five scenarios and all fifteen phrasing variants; `qwen2.5:3b-instruct` also
passes and is ~3× faster.

Warm, cached latency is **7.4 s (3B)** and **20.1 s (7B)**. Almost all of a cold
call is prompt evaluation, which the server caches after the first request, so
the stack pins the model in memory (`OLLAMA_KEEP_ALIVE=-1`) and warms it at
startup — otherwise an idle unload costs a 79 s stall on the next question.

`make llm-check` runs the agent's real prompts against your endpoint and reports
the negotiated structured-output mode, the schema-valid rate, the intent match
rate across the five scenarios and all fifteen phrasing variants, the repair rate
and latency — then gives a READY / MARGINAL / NOT READY verdict. **Structured-output
reliability matters more than model size**: every LLM step extracts into a Pydantic
model, so a small model that always returns valid JSON beats a large one that
sometimes does not.

Defaults live in `.env` (`LLM_PROVIDER=openai_compatible`,
`LLM_BASE_URL=http://localhost:11434/v1`). Setting `LLM_PROVIDER=anthropic` with
an API key is available as a development reference only.

**With no model reachable the agent falls back to deterministic rule-based
understanding** and labels every response `degraded: true`. That is deliberate:
even when the model fails to interpret a request, it cannot corrupt a factory
calculation or reach the database — the deterministic layer stays in control.

### Database tasks

| Command | Purpose |
|---------|---------|
| `make db-seed` | rebase the factory onto the current ISO week (idempotent) |
| `make db-verify` | run the 20 data assertions — expected vs actual vs PASS/FAIL |
| `make db-rehearse DATE=2026-09-11` | seed and verify as if today were that date, to rehearse a demo |
| `make db-reset` | destroy the volume and rebuild from scratch |
| `make db-shell` | open psql |
| `make llm-check` | check the local model is reliable enough to drive the agent |

### How the layers hold together

The database is seeded deterministically and verified by 20 SQL assertions; the
tool layer is verified by Python tests that reach the same numbers through a
completely different path. The agent plans against the tool registry, so a tool
it cannot name it cannot call. `db/verify.sql` stays the independent oracle for
the Day-6 calculation engine.

The dataset is deterministic and date-relative: every date derives from the current ISO week, so the
demo tells the same story whenever it is shown. `db/verify.sql` recomputes capacity, bottleneck,
machine health and plan-vs-actual in plain SQL as an independent oracle for the Day-6 engine —
**20/20 assertions pass Monday through Friday** (see [docs/05-seed-data.md](docs/05-seed-data.md) for
the weekend limitation).
