# 01 — Finalized Requirements & Scope

**Project:** Smart CNC Factory MES Copilot (prototype)
**Duration:** 10 days · **Type:** Prototype / capability demonstration
**Data:** Virtual (synthetic) CNC factory data — no real machine or MES connection

---

## 1. One-sentence goal

Prove the chain **Natural Language → AI Agent → Controlled MES Tools → Deterministic Calculation → Validated, Explainable Answer** on a virtual CNC factory.

## 2. The five things that must be provable

| # | Capability | How it is proven in the demo |
|---|-----------|------------------------------|
| 1 | Understands factory questions | 5 scenarios + incomplete/rewritten variants (`docs/04-demo-scenarios.md`) |
| 2 | Queries MES data | Every number in an answer is traceable to a tool call and a DB row |
| 3 | Performs controlled calculations | Capacity/bottleneck numbers come from Python functions, never from the LLM |
| 4 | Returns reliable answers | Validator rejects answers containing numbers not present in tool output |
| 5 | Explains itself | Every answer ships an "AI Analysis Steps" plan + "Data Used" source list |

## 3. Functional requirements (locked for the prototype)

### FR-1 Natural-language question intake
Factory manager types a free-text question in a web UI. English only for the prototype.

### FR-2 Request rewriting & clarification
- Incomplete question (`"How many A12 this week?"`) → internally rewritten to a canonical intent, and the rewrite is shown to the user.
- Genuinely ambiguous question → agent asks **one** clarifying question with concrete options
  (e.g. *maximum capacity / planned production / actual production*) instead of guessing.

### FR-3 Structured intent extraction
Question → typed object: `intent`, `entities` (parts, machines), `time_window`, `metric`, `confidence`.
Pydantic-validated; a failed parse becomes a clarification, not a hallucinated answer.

### FR-4 Multi-step agent planning
The agent produces an ordered plan **before** execution, executes it as tool calls, and the UI renders the plan as "AI Analysis Steps". Minimum: the capacity scenario must trigger ≥ 5 tool calls.

### FR-5 Controlled MES tool layer
The LLM has **no** SQL access and no arbitrary table access. Exactly these 8 tools:

| Tool | Purpose |
|------|---------|
| `get_machine_status(machine_id?)` | status, temperature, vibration, utilization, current job |
| `get_available_machines(machine_type?, time_window?)` | machines eligible + available hours in window |
| `get_part_information(part_id)` | cycle time, material, required machine type |
| `get_production_orders(part_id?, status?, time_window?)` | planned vs completed qty, due dates |
| `get_material_inventory(material_id?)` | on-hand quantity per material |
| `get_maintenance_schedule(machine_id?, time_window?)` | planned downtime in window |
| `get_production_history(part_id?, machine_id?, time_window?)` | produced / rejected / downtime per day |
| `calculate_production_capacity(part_id, time_window)` | **deterministic** capacity + bottleneck + breakdown |

Every tool returns a typed envelope: `{ data, sources[], missing_fields[], warnings[] }`.

### FR-6 Deterministic calculation & rule engine
Capacity, bottleneck ranking, and machine-health verdicts are pure Python functions over tool data.
Rule thresholds live in the database (`rule_thresholds`), not in prompts, so they are auditable.

### FR-7 Result validation
Before an answer reaches the user:
1. every numeric token in the answer must appear in the tool-result set (tolerance for rounding/formatting);
2. every cited machine/part id must exist in the retrieved data;
3. failure → the answer is regenerated once, then downgraded to a data-only response.

### FR-8 Missing-data handling
If a required field is `NULL` (e.g. B20 cycle time), the agent **refuses to calculate** and names the missing field and the tool that reported it. No estimation, no substitution.

### FR-9 Industrial domain restriction
Non-manufacturing requests are rejected with a fixed message:
> This AI assistant is restricted to Smart Factory, CNC, manufacturing and MES-related requests.

Guard runs **before** planning (cheap classifier + allow/deny heuristics), so no tools and no factory data are touched.

### FR-10 Web interface
Single page: live factory status strip (5 machines), question box, answer card with headline number, bottleneck, AI Analysis Steps, and Data Used list.

## 4. Non-functional requirements

| Area | Target for the prototype |
|------|--------------------------|
| Latency | ≤ 10 s end-to-end for the capacity scenario (streamed steps so the UI is never idle) |
| Determinism | Same question + same DB state → same numbers, always (LLM temperature 0 for planning; math outside the LLM) |
| Portability | Docker Compose; no managed cloud service required; must be able to run against a local/on-prem open-weight LLM |
| Observability | Every request logged with plan, tool calls, tool results, validation verdict |
| Security posture | Read-only DB role for tools; no dynamic SQL from LLM output |

## 5. Explicitly out of scope

Real ERPNext / MES / Siemens NX / PDM / CNC connectivity · G-code generation or execution · predictive-maintenance ML · digital twin · fine-tuning / LoRA / QLoRA · industrial RAG · knowledge graph · production optimization · multi-agent architecture · H200 deployment · air-gapped infrastructure · production-grade cybersecurity · authentication / multi-tenancy · mobile UI.

## 6. Acceptance criteria → verification

| # | Criterion | Verified by |
|---|-----------|-------------|
| 1 | NL understanding | All 5 scenarios + 3 phrasing variants each pass (`docs/04-demo-scenarios.md`) |
| 2 | Tool calling | Trace shows expected tool set per scenario |
| 3 | Multi-step reasoning | Capacity scenario executes ≥ 5 tools in one turn |
| 4 | Reliable calculation | Capacity unit test: fixed dataset → exact expected integer |
| 5 | Explainability | Answer lists data sources + steps for all 5 scenarios |
| 6 | Missing data | B20 capacity question returns refusal naming `cycle_time_min` |
| 7 | Domain restriction | "Write me a story" → fixed rejection, zero tool calls in trace |
| 8 | Demo quality | Full Demo 1–5 flow runs in the web app without manual DB edits |

## 7. Decisions taken on Day 1 (previously open)

| Question | Decision |
|---------|----------|
| Hero scenario | A12 weekly production capacity — everything else supports it |
| Product name | **Smart CNC Factory MES Copilot** |
| Agent framework | LangGraph state machine (deterministic node graph, easy to visualize as "Analysis Steps") |
| LLM | Provider-abstracted; dev on a hosted model, must run on a local open-weight model (documented in `docs/02-architecture.md`) |
| "This week" | Current ISO week, Monday 00:00 → Sunday 23:59, factory-local time; past days in the week are excluded from remaining capacity |
| Capacity semantics | *Maximum feasible* quantity, constrained by machine hours and material — not planned and not actual |
| Units | Cycle time in **minutes/part**, availability in **hours**, temperature °C, vibration mm/s |
| Machine eligibility | `parts.required_machine_type = machines.machine_type` and machine status ∈ {running, idle} |
