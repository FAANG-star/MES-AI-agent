# 08 — Multi-Step Execution

Code: [`backend/app/agent/executor.py`](../backend/app/agent/executor.py) ·
[`pipeline.py`](../backend/app/agent/pipeline.py) ·
[`tracing.py`](../backend/app/agent/tracing.py)
Tests: 40 new, 231 total.

Understanding produces a plan. Execution runs it, folds every result into one structured
object, streams the work as it happens, and writes the whole thing to the audit
trail.

## 1. The workflow

```
question
  ├─▶ understand   guard · rewrite · typed intent · entities · plan
  ├─▶ execute      each step through the controlled tool layer
  │                 · bindings resolved from earlier results
  │                 · required fields checked, or the run refuses
  └─▶ record       one row in agent_run_log
```

`ask()` returns the finished run. `stream()` yields the same work as it happens.
Both consume **one** execution path — the stream is a view of the work, not a
second implementation of it, so the two cannot drift apart. A test asserts they
produce the same steps and the same status.

## 2. The plan is the state machine

The plan arrives already ordered, already validated against the registry, with
dependencies declared rather than discovered. Execution is therefore a bounded
walk over a fixed list: it cannot loop, cannot call a tool that was not planned,
and cannot vary between two runs of the same question.

That is why there is no graph library here. The brief allows *"LangGraph or a
simple custom tool-calling agent"* (§14), and ADR-1 chose a fixed node graph for
its properties — reproducible traces, a natural step rendering, no runaway tool
loops. Those properties come from the plan being static and inspectable, which
understanding already delivers. A graph library on top would add a dependency and a layer
of indirection without adding a guarantee. **ADR-1 is amended, not abandoned: the
plan is the graph.**

## 3. Bindings carry values between steps

Step 2 needs the machine type step 1 returns. The plan declares that as a binding;
the executor resolves it by following the dotted path into the earlier envelope:

```
step 2  get_available_machines
        machine_type ← step 1 · data.part.required_machine_type = "CNC_LATHE"
step 4  get_material_inventory
        material_id  ← step 1 · data.part.material_id           = "STEEL-4140"
```

Every resolved binding is recorded on the step — the value, the step it came
from, and the path — so a reviewer can see not just what was called but *why it
was called with that argument*.

If the source value is absent, the step is marked `skipped` with the reason
rather than called with a null. A tool is never invited to guess.

## 4. Missing data stops the run, and the plan says which data

Each step declares the fields it must come back with:

```python
get_part_information   requires ["parts.cycle_time_min", "parts.material_qty_per_unit"]
get_material_inventory requires ["inventory.available_quantity"]
```

If a tool reports one of those in `missing_fields`, the run stops with
`refused_missing_data`, names the field, and marks the remaining steps `skipped`
— which keeps the whole plan visible in the panel while making it obvious that
nothing was computed.

This is FR-8 expressed as data rather than as a special case in code, and it is
what makes the distinction correct: **CNC-02's offline vibration sensor must not
refuse a capacity question, while B20's missing cycle time must.** Both are NULLs
in the same MES; only one is required by the plan that is running. A test asserts
each behaviour.

## 5. A tool that is not built yet is not a failure

Before the calculation engine existed, `calculate_production_capacity` recorded
`not_implemented`: the run continued and completed, and the answer said plainly
that the number was not available rather than fabricating a total. `headline`
stayed `null`.

The mechanism remains — it is the same discipline as the missing-data path,
applied to the system's own incompleteness — but the capacity step now returns a
number, and the executor appends a step 6 (`kind: "engine"`) that derives the
headline and the bottleneck from it. See
[`09-calculation-engine.md`](09-calculation-engine.md).

## 6. Structured results

One `AgentRun` carries everything the UI renders and the audit trail keeps:

```jsonc
{
  "run_id": "…", "status": "answered",
  "question": "How many A12 parts can we produce this week?",
  "rewritten_question": "Calculate the maximum feasible A12 production…",
  "intent": "production_capacity", "metric": "max_capacity",
  "window": { "start": "2026-09-09", "end": "2026-09-13", … },
  "answer": "…assembled from the step summaries…",
  "answer_is_generated": true,       // the explainer wrote it
  "headline":   { "label": "Estimated A12 capacity", "value": 1139, "unit": "units" },
  "bottleneck": { "machine_id": "CNC-03", "reason": "18.5 effective hours — …" },
  "capacity":   { /* the full breakdown, with its formula */ },
  "constraint": { /* machine | material | none, with the ranking */ },
  "steps":   [ { "step": 1, "tool": "…", "status": "ok", "summary": "…",
                 "arguments": {…}, "resolved_bindings": {…}, "sources": [ … ] } ],
  "sources": [ { "table": "parts", "fields": […], "keys": ["A12"], "rows": 1 } ],
  "missing_fields": [], "validation": { "grounded": true, "retries": 0 },
  "elapsed_ms": 13712
}
```

`sources` is merged across steps — one entry per table, with the union of the
fields and entity ids every step touched. That is the "Data Used" panel, and it
is assembled from what the tools reported, never written by a model.

`answer` is composed deterministically from the step summaries, each of which is
built from the returned data. The explainer puts the model's wording on top of it,
validated against the tool results before anyone sees it; `answer_is_generated`
says which one you are looking at, and the deterministic text is what a failed
validation falls back to. Either way, every figure in the answer is something a
tool or the engine actually produced — see
[`10-reliability.md`](10-reliability.md).

## 7. Streaming

`POST /api/ask/stream` emits server-sent events: `accepted`, `understanding`,
`tool_result` per step, `answer` once the explanation is written and validated,
`error` if a step fails, and `run` with the complete result.

Measured on the composed stack with the local 3B model, on an earlier build in
which the capacity step was not yet implemented:

```
[  0.1s] accepted
[ 13.7s] understanding  intent=production_capacity plan=5
[ 13.7s] step 1/5  get_part_information           ok
[ 13.7s] step 2/5  get_available_machines         ok
[ 13.8s] step 3/5  get_maintenance_schedule       ok
[ 13.8s] step 4/5  get_material_inventory         ok
[ 13.8s] step 5/5  calculate_production_capacity  not_implemented
[ 13.8s] run            answered, 13712ms
```

The shape of that timeline is the point. Understanding is the slow part — one
local model call — and the tool calls are milliseconds. Streaming means the UI
acknowledges the question immediately and fills the analysis panel the moment
work completes, instead of showing nothing for fourteen seconds.

## 8. The audit trail

Every run is written to `agent_run_log`: question, rewrite, intent, resolved
entities, the plan, every tool call with its arguments and sources, the answer,
the status and the latency.

It is written over the **application's own read-write connection**, never the
tool pool. ADR-6 gives `mes_ro` SELECT only, with no exception carved into it —
so the read-only guarantee on the tool path stays absolute, and the audit trail
is what the application says it did.

Writing is best-effort: a failure to record is logged and noted on the run, but
never fails the answer. A test asserts a run still succeeds with the audit log
unavailable.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/traces` | recent runs, newest first |
| `GET` | `/api/traces/{run_id}` | the full trace of one question |

This is the evidence behind acceptance criteria 2, 5 and 7 — and the backup slide
if a live demo run misbehaves.

## 9. Verified against the seeded factory

On an earlier build, before the calculation engine and on the original dataset:

| Question | Status | Tool calls | Notes |
|---|---|---|---|
| How many A12 parts can we produce this week? | `answered` | 4 + 1 pending | 5 sources; capacity step pending |
| Can CNC-03 continue production today? | `answered` | 2 | cites `rule_thresholds` |
| Which CNC machine is limiting A12 production? | `answered` | 3 + 1 pending | no inventory step |
| Why was A12 production lower yesterday? | `answered` | 3 | planned 250 / produced 215 / rejected 8 / downtime 2.1 h |
| Which machine needs maintenance attention? | `answered` | 2 | CNC-02's NULL sensor noted, not fatal |
| How many B20 parts can we produce tomorrow? | `refused_missing_data` | 1 | names `parts.cycle_time_min` |
| What is the status of CNC-09? | `answered` | 1 | "does not exist", from the tool result |
| Write me a story. | `rejected_out_of_domain` | **0** | nothing read |

The S4 chain is worth noting: the maintenance step reports *"1 completed
maintenance record: CNC-02"*, so the 2.1 h of downtime in `production_history` is
corroborated by a second table rather than asserted. The first version of that
step summary said "no maintenance scheduled" — technically true, since a
completed record carries no scheduled hours, and exactly the kind of true
statement that hides the cause. Testing the real question found it.

### Tests

| File | Covers |
|------|--------|
| `test_execution.py` | 21 — the documented sequences, bindings, the missing-data refusal and what must *not* trigger it, the pending step, source merging, reproducibility, stream/collected agreement |
| `test_tracing.py` | 9 — round-trip, plan and tool calls recorded, rejected runs logged with zero calls, survival when the log is unavailable |
| `test_api.py` | +10 — `/api/ask`, SSE event order, trace endpoints, 404 and 422 paths |

## 10. The calculation engine

Nothing in this layer had to change to accommodate the calculation engine: the executor gained a derivation phase after the tool
loop, and the capacity step began returning a number instead of a `501`. See
[`09-calculation-engine.md`](09-calculation-engine.md).
