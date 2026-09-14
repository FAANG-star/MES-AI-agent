# Smart CNC Factory MES Copilot

Prototype industrial AI agent for a virtual CNC factory:

**Natural language → AI agent → controlled MES tools → deterministic calculation → validated, explainable answer.**

> The LLM understands the question, plans the steps and explains the result.
> It never touches the database and never produces a number.
> It runs **locally**, so factory data never leaves the application environment.

## Status

| Area | Deliverable | Status |
|------|-------------|--------|
| Foundations | Requirements · architecture · DB schema · demo questions | ✅ done |
| Virtual MES | Seed data + 20 data assertions | ✅ done |
| Tool layer | 8 controlled MES tools + FastAPI | ✅ done |
| Understanding | Domain guard, rewriting, intent extraction, tool selection | ✅ done |
| Execution | Multi-step plan execution, structured results, audit trail | ✅ done |
| Calculation | Capacity, bottleneck, machine-health rules, plan vs actual | ✅ done |
| Reliability | Missing data, domain restriction, validation, explanation | ✅ done |
| Web interface | AI chat, machine summary, result cards, data sources | ✅ done |
| Testing | The full demo matrix live; fixes for tool selection, hallucinations, calculations, UI | ✅ done |
| Final demo package | Walkthrough, sample dataset, architecture summary | next |

## Documentation

| Doc | Contents |
|-----|----------|
| [docs/01-requirements.md](docs/01-requirements.md) | Finalised functional/non-functional requirements, scope, acceptance criteria, scoping decisions |
| [docs/02-architecture.md](docs/02-architecture.md) | System diagram, request lifecycle, components, ADRs, capacity algorithm spec, API surface |
| [docs/03-database-schema.md](docs/03-database-schema.md) | ER model, table-by-table rationale, deviations from the requirement, seed-data plan |
| [docs/04-demo-scenarios.md](docs/04-demo-scenarios.md) | The 5 scenarios + reliability cases, expected tool sequences, pass criteria, demo order |
| [docs/05-seed-data.md](docs/05-seed-data.md) | The virtual factory dataset: what every value is for, verified numbers, known limits |
| [docs/06-mes-tools.md](docs/06-mes-tools.md) | The 8 controlled tools: envelope contract, time windows, security posture, HTTP surface |
| [docs/07-agent-understanding.md](docs/07-agent-understanding.md) | Domain guard, request rewriting, typed intent, entity grounding, tool selection, LLM providers |
| [docs/08-multi-step-execution.md](docs/08-multi-step-execution.md) | Executing the plan: bindings, missing-data refusal, structured results, streaming, audit trail |
| [docs/09-calculation-engine.md](docs/09-calculation-engine.md) | Capacity, bottleneck, health rules and plan-vs-actual — pure Python, cross-checked against the SQL oracle |
| [docs/10-reliability.md](docs/10-reliability.md) | Refusal, domain restriction, answer validation and the generated explanation — and why grounded is not the same as correct |
| [docs/11-frontend.md](docs/11-frontend.md) | The web interface: streamed analysis steps, the four answer cards, why the UI computes nothing |
| [docs/12-testing.md](docs/12-testing.md) | The demo script as an executable matrix, run live against the local model — and every defect it found |

## The five demo scenarios

1. **Capacity (hero)** — *How many A12 parts can we produce this week?*
2. **Machine health** — *Can CNC-03 continue production today?*
3. **Bottleneck** — *Which CNC machine is limiting A12 production?*
4. **Analysis** — *Why was A12 production lower yesterday?*
5. **Maintenance** — *Which machine needs maintenance attention?*

Plus reliability: request rewriting, clarification, missing-data refusal, out-of-domain rejection.

## Stack

Next.js 16 + React 19 + Tailwind 4 · FastAPI (Python 3.12) + Pydantic · PostgreSQL 16 · Docker Compose.

The browser talks only to the Next.js server, which proxies a fixed list of API
routes — so there is no public API URL, no CORS, and the controlled-surface
principle of the tool layer holds one level up as well.

**The language model runs locally.** The prototype uses a locally deployed
open-weight model behind an OpenAI-compatible endpoint (Ollama / vLLM), so
factory questions and MES data stay inside the application environment — the
architecture the factory's isolated production network will need. The LLM
handles natural-language understanding and explanation; production calculations
and factory rules are executed by deterministic backend services.

## Getting started

```bash
make env          # copy .env.example to .env (factory timezone is Asia/Tokyo)
make up           # the whole stack → http://localhost:3000
make test         # 395 backend tests, including the whole demo script
make web-test     # 59 frontend unit tests
make db-verify    # 20 data assertions over the seeded factory

make test-week    # every backend test + the SQL oracle, once as each day of this week
make scenarios    # the demo script against the live stack and the local model
make web-e2e      # 10 browser tests against the running stack
```

Then open **http://localhost:3000**, or drive the same run from the terminal:

```bash
# Ask the factory — understand, plan, execute, record
curl -s -X POST localhost:8000/api/ask \
     -H 'content-type: application/json' \
     -d '{"question":"How many A12 can we produce this week?"}'

# The same run, streamed step by step as it happens
curl -N -X POST localhost:8000/api/ask/stream \
     -H 'content-type: application/json' \
     -d '{"question":"How many A12 can we produce this week?"}'

curl -s localhost:8000/api/traces                    # recent runs (audit trail)

# Understanding only — what it means and how it plans, nothing executed
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
| `make db-rehearse DATE=2026-09-18` | seed and verify as if today were that date; pair with `FACTORY_TODAY=2026-09-18 make up` to rehearse a demo end to end |
| `make db-reset` | destroy the volume and rebuild from scratch |
| `make db-shell` | open psql |
| `make factory-timezone ZONE=Asia/Shanghai` | move the factory to another time zone (validates, reseeds, restarts the backend) |
| `make llm-check` | check the local model is reliable enough to drive the agent |

### How the layers hold together

The database is seeded deterministically and verified by 20 SQL assertions; the
tool layer is verified by Python tests that reach the same numbers through a
completely different path. The agent plans against the tool registry, so a tool
it cannot name it cannot call. And the calculation engine is checked against
`db/verify.sql` on live data — **two implementations, two languages, one
specification, required to agree exactly.** That cross-check has already caught
one real divergence and one unspecified corner (see
[docs/09](docs/09-calculation-engine.md) §6).

The dataset is deterministic and date-relative: every date derives from the current ISO week, so the
demo tells the same story whenever it is shown. `db/verify.sql` recomputes capacity, bottleneck,
machine health and plan-vs-actual in plain SQL as an independent oracle for the calculation engine —
**20/20 assertions pass on every day of the week**, and `make test-week` runs the whole backend suite
as each of those days (see [docs/05-seed-data.md](docs/05-seed-data.md)).

### What a question returns today

The same run, in the browser: the headline figure, the sentence the local model
wrote about it, the arithmetic underneath, the steps that produced it — each
labelled **MES tool**, **Calculation** or **Language model** — and the tables
every figure came from.

```
Q  How many A12 parts can we produce this week?          (asked on a Monday)

A  We can produce up to 4388 A12 parts this week, limited by CNC-03's 32 available
   hours.

Estimated A12 capacity: 4,388 units          validated · grounded · 0 retries
Bottleneck: CNC-03 — 32 effective hours — a shorter shift pattern (56 planned hours,
            against 112 planned hours on other machines) and 24 h of scheduled maintenance
Data Used: inventory, machine_shift_calendar, machines, maintenance, parts
Working: machine capacity = 1920 + 1920 + 548 = 4388 · material = floor(9600 ÷ 1)
         = 9600 · final = min(4388, 9600) = 4388 (machine-constrained)
```

The sentence is written by the local model. Every number in it comes from a pure
Python function with unit tests, and is checked back against the tool results
before you see it — if a figure is not in the data, the answer is regenerated
once and then replaced by the deterministic one. The language model chose which
question was being asked and how to say the result; it did not produce a single
figure.

**Grounded is not the same as correct.** Asked for this week's A12 capacity, the
model once answered "317" — one machine's contribution to the 1,139 total. Every
digit was real. So the validator also requires the *principal finding*: the
calculated figure, the machine that was named, the verdict that was reached.
See [docs/10-reliability.md](docs/10-reliability.md) §4.
