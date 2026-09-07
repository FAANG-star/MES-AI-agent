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
  ├─▶ Planner .............................. 8 steps (shown in UI)
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

## 3. Component responsibilities

| Component | LLM? | Responsibility | Fails how |
|-----------|------|----------------|-----------|
| Domain Guard | small/cheap call + keyword allowlist | in-domain vs out-of-domain | Fail **closed** → fixed rejection message |
| Rewriter | yes | expand elliptical questions; flag ambiguity | Ambiguous → clarifying question |
| Intent Extractor | yes (structured output) | typed intent/entities/time window | Parse error → clarifying question |
| Planner | yes (constrained) | ordered subset of the 8 tools | Unknown tool name → step dropped, logged |
| Tool Executor | no | run tools, collect sources, collect `missing_fields` | Missing field → short-circuit to refusal |
| Calc / Rule Engine | **no** | capacity, bottleneck, health verdicts | Raises typed error, never guesses |
| Validator | no | numeric + entity grounding of the draft answer | 1 retry → then data-only answer |
| Explainer | yes | natural-language answer from tool results only | — |

## 4. Key design decisions (ADRs, condensed)

**ADR-1 — LangGraph over free-form ReAct.**
The demo must *show* deterministic steps. A fixed node graph with a bounded tool loop gives reproducible traces, a natural "AI Analysis Steps" rendering, and no runaway tool loops. Free-form ReAct would vary run-to-run in front of the factory manager.

**ADR-2 — Tool layer instead of text-to-SQL.**
The client's stated architecture is `LLM → controlled tools → factory systems`. Text-to-SQL cannot be validated, cannot enforce units, and is unsafe on a real MES. The 8 tools are the contract; the DB schema can change behind them.

**ADR-3 — Math outside the LLM.**
`calculate_production_capacity` is a pure function with unit tests. The LLM is forbidden from arithmetic; the validator enforces it. This is acceptance criterion 4.

**ADR-4 — Thresholds and business rules in the database.**
`rule_thresholds` (temp 70 °C, vibration 2.5 mm/s, …) is queried, cited as a source, and changeable without touching prompts or code — closer to how a real plant tunes limits.

**ADR-5 — Provider-abstracted LLM.**
One `LLMClient` interface (`complete`, `structured`) with two implementations: a hosted model for development and an OpenAI-compatible local endpoint (vLLM / Ollama) for the on-prem path. Nothing above the interface knows which is in use, so the future air-gapped deployment is a config change.

**ADR-6 — Read-only DB role for the tool layer.**
Tools connect as `mes_ro`. Even a compromised prompt cannot mutate factory data.

**ADR-7 — Shift calendar as the source of availability.**
`machine_shift_calendar(machine_id, shift_date, planned_hours)` lets the same code answer "today", "tomorrow", and "this week". `machines.available_hours` is kept as a denormalized display field only (the requirement lists it) and is never used in the capacity math.

**ADR-8 — RocketRide not used for the core agent.**
This workspace ships RocketRide pipeline tooling, which targets document/RAG/ETL pipelines. The core requirement is a deterministic tool-calling agent over a relational MES with auditable arithmetic; the requirement document also pins FastAPI + LangGraph + PostgreSQL. RocketRide remains a candidate for a later document-intelligence extension (work instructions, drawings, maintenance manuals), which is out of scope here.

## 5. Capacity algorithm (specification — implemented Day 6)

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
├─ docs/                     01 requirements · 02 architecture · 03 schema · 04 scenarios
├─ db/
│  ├─ schema.sql             DDL (Day 1 — done)
│  └─ seed.sql               synthetic factory data (Day 2)
├─ backend/
│  ├─ app/
│  │  ├─ main.py             FastAPI app, /api/ask (SSE), /api/machines
│  │  ├─ agent/              graph.py · guard.py · rewriter.py · planner.py · validator.py
│  │  ├─ tools/              the 8 MES tools + typed envelopes
│  │  ├─ engine/             capacity.py · rules.py · bottleneck.py  (pure, unit-tested)
│  │  ├─ repositories/       SQL, read-only
│  │  ├─ llm/                provider abstraction
│  │  └─ schemas/            Pydantic models
│  └─ tests/                 engine unit tests + 5 scenario tests
├─ frontend/                 Next.js app (Day 8)
├─ docker-compose.yml        postgres + backend + frontend
└─ .env.example
```

## 7. API surface (draft)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/health` | liveness |
| `GET` | `/api/machines` | factory status strip |
| `POST` | `/api/ask` | question → SSE stream: `step`, `tool_result`, `answer`, `error` |
| `GET` | `/api/traces/{id}` | full audit trace of one question (demo/debug) |

`POST /api/ask` response payload:
```jsonc
{
  "answer": "The estimated maximum production capacity for A12 this week is 1,240 units...",
  "headline": { "label": "Estimated A12 Capacity", "value": 1240, "unit": "units" },
  "bottleneck": { "machine_id": "CNC-03", "reason": "18.0 effective hours (maintenance)" },
  "steps": [ { "n": 1, "title": "Get A12 information", "tool": "get_part_information", "status": "ok" } ],
  "sources": [ { "table": "parts", "keys": ["A12"], "fields": ["cycle_time_min"] } ],
  "validation": { "grounded": true, "retries": 0 },
  "status": "answered"        // answered | clarify | refused_missing_data | rejected_out_of_domain
}
```
