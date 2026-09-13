# 02 — Architecture

## 1. System overview

```
┌──────────────────────────────────────────────────────────────┐
│  Frontend — Next.js 14 (App Router) + React + Tailwind       │
│  · Factory status strip   · Question box                     │
│  · AI Analysis Steps (streamed)   · Answer card + sources    │
└───────────────┬──────────────────────────────────────────────┘
                │  POST /api/ask   (SSE stream of step events)
┌───────────────▼──────────────────────────────────────────────┐
│  Backend — FastAPI (Python 3.12)                             │
│                                                              │
│   ┌────────────────────────────────────────────────────┐     │
│   │ 1. Domain Guard        (reject non-factory)        │     │
│   │ 2. Rewriter            (complete the question)     │     │
│   │ 3. Intent Extractor    (Pydantic structured out)   │     │
│   │ 4. Planner             (ordered step list)         │     │
│   │ 5. Tool Executor       (8 MES tools only)          │───┐ │
│   │ 6. Calc / Rule Engine  (pure Python, no LLM)       │   │ │
│   │ 7. Validator           (numbers ⊂ tool results)    │   │ │
│   │ 8. Explainer           (NL answer + sources)       │   │ │
│   └────────────────────────────────────────────────────┘   │ │
│              LangGraph state machine                        │ │
└───────────────┬─────────────────────────────────────────────┼─┘
                │ read-only SQL (repository layer)            │
┌───────────────▼─────────────────────┐        ┌──────────────▼──┐
│  PostgreSQL 16 — virtual MES         │        │  LLM provider   │
│  machines · parts · orders ·         │        │  (abstracted)   │
│  inventory · maintenance ·           │        │  temp 0         │
│  production_history · shifts · rules │        └─────────────────┘
└──────────────────────────────────────┘
```

**Hard rule:** the LLM never sees the database and never emits SQL. It only chooses among 8 typed tools. Numbers are produced by Python, described by the LLM.

## 2. Request lifecycle (hero scenario)

```
"How many A12 can we produce this week?"
  │
  ├─▶ Domain Guard ......................... in-domain ✓ (0 tool calls if rejected)
  ├─▶ Rewriter ............................. "Calculate the maximum feasible A12 production
  │                                           quantity for the current ISO week using
  │                                           available CNC resources."
  ├─▶ Intent Extractor ..................... {intent: production_capacity,
  │                                            parts:[A12], window: this_week,
  │                                            metric: max_capacity, confidence: 0.94}
  ├─▶ Planner .............................. 8 steps (shown in UI; 1-6 built)
  │      1 get_part_information(A12)
  │      2 get_available_machines(type=required_machine_type, window)
  │      3 get_maintenance_schedule(window)
  │      4 get_material_inventory(material of A12)
  │      5 calculate_production_capacity(A12, window)
  │      6 bottleneck ranking
  │      7 validate
  │      8 explain
  ├─▶ Tool Executor ........................ typed envelopes + source records
  ├─▶ Calc Engine .......................... capacity = 1,240 · bottleneck = CNC-03
  ├─▶ Validator ............................ every number in draft ∈ tool results ✓
  └─▶ Answer + Steps + Data Used ........... streamed to UI
```

Steps 1–5 are tool calls and are what `Understanding.plan` contains — the Day-4
planner produces them, the Day-5 executor runs them. Steps 6–8 are not tool calls
and never appear in the plan: the ranking (Day 6) is `kind: "engine"`, the
explanation (Day 7) is `kind: "llm"`, and the validation (Day 7) is
`kind: "engine"` again. All eight are in the trace, and `tool_call_count` still
reports **5** — counting a calculation as a tool call would inflate the one
number the audit trail exists to keep honest.

## 3. Component responsibilities

| Component | LLM? | Responsibility | Fails how |
|-----------|------|----------------|-----------|
| Domain Guard | only when heuristics are inconclusive **or contested** | in-domain vs out-of-domain | Fail **closed** → fixed rejection message |
| Rewriter + Intent Extractor | yes (one structured call) | rewrite, typed intent, entities, window, ambiguity | Ambiguous or unparsable → clarifying question; provider down → deterministic rules |
| Entity Resolver | **no** | ids checked against the MES | Unknown id flagged, plan continues |
| Planner | model proposes, template guarantees, registry validates | ordered subset of the 8 tools | Unknown tool name → step dropped, logged |
| Tool Executor | no | run tools, collect sources, collect `missing_fields` | Missing field → short-circuit to refusal |
| Calc / Rule Engine | **no** | capacity, bottleneck, health verdicts | Raises typed error, never guesses |
| Explainer | yes (one completion) | natural-language answer, from a fact sheet and nothing else | Model down or slow → the deterministic answer stands |
| Validator | **no** | numeric + entity grounding, **and** the run's principal finding must be stated | 1 retry with the fault named → then the data-only answer |

## 4. Key design decisions (ADRs, condensed)

**ADR-1 — A fixed, inspectable plan rather than free-form ReAct.** *(amended Day 5)*
The demo must *show* deterministic steps. A fixed graph with a bounded tool loop gives reproducible traces, a natural "AI Analysis Steps" rendering, and no runaway tool loops. Free-form ReAct would vary run-to-run in front of the factory manager.

**Amendment (Day 5): the plan is the graph, and no graph library is used.** By the time execution starts, the plan is already ordered, already validated against the registry, and carries its dependencies as declared bindings — so running it is a bounded walk over a fixed list that cannot loop, cannot call an unplanned tool, and cannot vary between two runs. Every property ADR-1 wanted is already held by the plan. The brief allows "LangGraph or a simple custom tool-calling agent" (§14); adding a graph library on top of a static graph would add a dependency and an indirection without adding a guarantee. See [`08-multi-step-execution.md`](08-multi-step-execution.md) §2.

**ADR-2 — Tool layer instead of text-to-SQL.**
The client's stated architecture is `LLM → controlled tools → factory systems`. Text-to-SQL cannot be validated, cannot enforce units, and is unsafe on a real MES. The 8 tools are the contract; the DB schema can change behind them.

**ADR-3 — Math outside the LLM.** *(implemented Day 6)*
`calculate_production_capacity` is a pure function with unit tests. The LLM is forbidden from arithmetic; the validator enforces it. This is acceptance criterion 4.

Delivered in `app/engine/` — capacity, bottleneck, condition rules and plan-versus-actual, all pure functions with no database, model or clock. Arithmetic is `Decimal`, not float, so it agrees exactly with the SQL oracle in `db/verify.sql`; `test_engine_oracle.py` runs both over live data and requires that agreement. The derivation is recorded in the trace as `kind: "engine"` and excluded from `tool_call_count`, because a calculation is not a tool call.

**ADR-4 — Thresholds and business rules in the database.**
`rule_thresholds` (temp 70 °C, vibration 2.5 mm/s, …) is queried, cited as a source, and changeable without touching prompts or code — closer to how a real plant tunes limits.

**ADR-5 — Provider-abstracted LLM, local-first.** *(implemented Day 4)*
One `LLMClient` interface (`structured`, `complete`). The **primary provider is a locally deployed open-weight model** behind an OpenAI-compatible endpoint (Ollama / vLLM / llama.cpp): the factory's production environment is isolated, so questions and MES data never leave the application environment, and the prototype's architecture is the one the real deployment needs. Claude via the official SDK remains available as an optional development reference and is an extra dependency, not part of the delivered stack.

Structured-output reliability — not model size — is the binding constraint, since every LLM step extracts into a Pydantic model. The local client negotiates `json_schema` → `json_object` → prompt-only, recovers JSON from code fences or surrounding prose, and retries once with the validation error before giving up; `make llm-check` measures all of this against a real endpoint. `temperature` is 0 for the local provider (current Claude models reject the parameter entirely).

**No provider is a supported third state**: the agent falls back to deterministic rule-based understanding, labels the response `degraded: true`, and keeps answering. The endpoint is probed once at startup so an unreachable model costs no per-request timeout. The claim this buys is worth more than uptime: even when the model fails to interpret a request, it cannot corrupt a calculation or reach the database — the deterministic layer stays in control.

**ADR-9 — Tool selection: model-proposed, template-guaranteed, registry-validated.** *(Day 4)*
The model is given the live tool catalogue and names the tools a question needs. A per-intent template then guarantees the sequence each demo scenario depends on, in an order where every step's inputs exist; extra tools the model asks for and the registry recognises are appended, and unrecognised names are dropped and logged. A purely model-chosen plan varies run to run — untestable against the fixed sequences in `04-demo-scenarios.md` and unsafe in a live demo — while a purely fixed plan would not be an agent. This keeps the judgement with the model and the reproducibility with the code.

**ADR-6 — Read-only DB role for the tool layer.** *(implemented Day 3)*
Tools connect as `mes_ro`: SELECT grants only, plus `default_transaction_read_only`, so writes fail at the transaction level even if a grant were wrong. The role is created idempotently by `db/schema.sql`, and `backend/tests/test_readonly.py` asserts DELETE/UPDATE/INSERT/DROP are all refused on the live connection. Tightened from the original sketch: `mes_ro` has **no** INSERT on `agent_run_log` — the Day-5 audit trail is written over the application's own read-write connection, leaving the tool path with no write capability at all.

**ADR-7 — Shift calendar as the source of availability.**
`machine_shift_calendar(machine_id, shift_date, planned_hours)` lets the same code answer "today", "tomorrow", and "this week". `machines.available_hours` is kept as a denormalized display field only (the requirement lists it) and is never used in the capacity math.

**ADR-8 — RocketRide not used for the core agent.**
This workspace ships RocketRide pipeline tooling, which targets document/RAG/ETL pipelines. The core requirement is a deterministic tool-calling agent over a relational MES with auditable arithmetic; the requirement document also pins FastAPI + LangGraph + PostgreSQL. RocketRide remains a candidate for a later document-intelligence extension (work instructions, drawings, maintenance manuals), which is out of scope here.

## 5. Capacity algorithm *(implemented Day 6 — see [`09-calculation-engine.md`](09-calculation-engine.md))*

```
window            = [start_date, end_date]           # ISO week or single day
eligible(m)       = m.machine_type == part.required_machine_type
                    AND m.status IN ('running','idle')

planned_h(m)      = Σ machine_shift_calendar.planned_hours   over window
maint_h(m)        = Σ maintenance.duration_hours             over window, status IN ('scheduled','in_progress')
effective_h(m)    = max(0, planned_h(m) - maint_h(m))

machine_capacity  = Σ over eligible(m):  floor( effective_h(m) * 60 / part.cycle_time_min )
material_capacity = floor( inventory.available_quantity / part.material_qty_per_unit )

final_capacity    = min(machine_capacity, material_capacity)

constraint        = 'material' if material_capacity < machine_capacity else 'machine'
bottleneck        = the eligible machine with the lowest effective_h   (reported when constraint = 'machine')
```

Preconditions — any failure returns a **refusal**, not a number:
`part.cycle_time_min IS NOT NULL` · `part.material_qty_per_unit IS NOT NULL` · at least one eligible machine · inventory row exists for the part's material.

Machine-health rules (Scenario 2 / 5), thresholds from `rule_thresholds`:
`temperature_c ≥ 70 → warning` · `vibration_mm_s ≥ 2.5 → warning` · `status = 'maintenance'` or an active maintenance window → **cannot produce**. Attention score = number of breached thresholds, ties broken by the largest relative breach.

## 6. Repository layout (target)

```
MES-ai-agent/
├─ docs/                     01 requirements · 02 architecture · 03 schema ·
│                            04 scenarios · 05 seed data · 06 MES tools
├─ db/
│  ├─ schema.sql             DDL + the read-only mes_ro role   (Day 1, 3 — done)
│  ├─ seed.sql               synthetic factory data            (Day 2 — done)
│  └─ verify.sql             20 data assertions / SQL oracle   (Day 2 — done)
├─ backend/                                                    (Day 3 — done)
│  ├─ app/
│  │  ├─ main.py             FastAPI app + lifespan
│  │  ├─ config.py           settings from .env
│  │  ├─ db.py               asyncpg pool, connected read-only
│  │  ├─ timewindow.py       factory-local window resolution
│  │  ├─ api/routes.py       /api/health · /api/machines · /api/tools
│  │  ├─ tools/              registry.py + the 8 MES tools
│  │  ├─ repositories/       fixed, parameterised read-only SQL
│  │  ├─ schemas/            envelope · MES models · tool payloads
│  │  ├─ agent/              guard · extractor · entities · selector ·
│  │  │                      understanding (Day 4) · executor · pipeline ·
│  │  │                      tracing (Day 5) · derive (Day 6) ·
│  │  │                      explainer · validator · answering (Day 7)
│  │  ├─ engine/             capacity · bottleneck · rules · analysis        (Day 6)
│  │  └─ llm/                anthropic · openai-compatible · factory          (Day 4)
│  ├─ tests/                 310 tests: windows · tools · API · read-only ·
│  │                         guard · extractor · understanding · llm ·
│  │                         execution · tracing · engine · engine-vs-oracle ·
│  │                         validation
│  └─ Dockerfile
├─ frontend/                                                   (Day 8 — done)
│  ├─ app/                   page · layout · api/mes proxy to the backend
│  ├─ components/            header · factory status · ask box · answer card ·
│  │                         analysis steps · evidence panels · data used
│  ├─ lib/                   types (mirroring the API) · sse · steps · format
│  ├─ tests/                 48 tests: sse parsing · step merging · run stage · formatting · theme
│  └─ Dockerfile             standalone build, no node_modules at runtime
├─ Makefile                  db + backend + stack tasks
├─ docker-compose.yml        postgres · model server · backend · frontend
└─ .env.example
```

## 7. API surface (draft)

| Method | Path | Purpose | Status |
|--------|------|---------|--------|
| `GET` | `/api/health` | liveness, factory clock, DB user + read-only flag, tool counts | ✅ Day 3 |
| `GET` | `/api/machines` | factory status strip | ✅ Day 3 |
| `GET` | `/api/tools` | tool catalogue with LLM-ready JSON schemas | ✅ Day 3 |
| `GET` | `/api/tools/{name}` | one tool's contract | ✅ Day 3 |
| `POST` | `/api/tools/{name}` | invoke a MES tool | ✅ Day 3 |
| `POST` | `/api/understand` | question → guard, rewrite, typed intent, entities, plan (nothing executed) | ✅ Day 4 |
| `GET` | `/api/agent` | active LLM provider, intents, pipeline stages | ✅ Day 4 |
| `POST` | `/api/ask` | question → the complete structured run | ✅ Day 5 |
| `POST` | `/api/ask/stream` | the same run as SSE: `accepted`, `understanding`, `tool_result`, `answer`, `error`, `run` | ✅ Day 5 · `answer` added Day 7 |
| `GET` | `/api/traces` | recent runs | ✅ Day 5 |
| `GET` | `/api/traces/{id}` | full audit trace of one question (demo/debug) | ✅ Day 5 |

The web interface reaches all of these through its own server
(`/api/mes/*` → the backend), so the browser has one origin and the backend
needs no public URL. See [`11-frontend.md`](11-frontend.md) §3.

The tool contract and envelope are documented in [`06-mes-tools.md`](06-mes-tools.md).

`POST /api/ask` response payload:
```jsonc
{
  "answer": "The estimated maximum production capacity for A12 this week is 1,240 units...",
  "headline": { "label": "Estimated A12 Capacity", "value": 1240, "unit": "units" },
  "bottleneck": { "machine_id": "CNC-03", "reason": "18.0 effective hours (maintenance)" },
  "steps": [ { "n": 1, "title": "Get A12 information", "tool": "get_part_information", "status": "ok" } ],
  "sources": [ { "table": "parts", "keys": ["A12"], "fields": ["cycle_time_min"] } ],
  "answer_is_generated": true,   // the local model wrote it; false = deterministic fallback
  "validation": { "grounded": true, "retries": 0, "note": "…what was checked…" },
  "status": "answered"        // answered | clarify | refused_missing_data | rejected_out_of_domain
}
```
