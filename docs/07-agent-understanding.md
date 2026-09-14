# 07 — Request Understanding

Code: [`backend/app/agent/`](../backend/app/agent) · [`backend/app/llm/`](../backend/app/llm)
Tests: 121 new, 183 total.

Understanding is the front half of the agent: what the factory manager meant,
and which MES calls would answer it. Nothing is executed here — no tool runs, no
number is produced. The executor runs the plan this produces
([`08-multi-step-execution.md`](08-multi-step-execution.md)).

That split is deliberate. It is what lets the UI show the plan **before** the
work happens, which is the "AI Analysis Steps" panel the demo is built around.

## 1. The pipeline

```
"How many A12 this week?"
  │
  ├─▶ Domain guard ............ in-domain?  no → fixed rejection, zero MES reads
  ├─▶ Rewrite + intent ........ one structured call → ExtractedIntent
  │                             ambiguous? → one clarifying question, no plan
  ├─▶ Entity resolution ....... A12 / CNC-03 checked against the real factory
  └─▶ Tool selection .......... ordered plan, arguments and bindings declared
```

Three outcomes, all first-class: **understood** with a plan, **clarify** with one
question and concrete options, **rejected_out_of_domain**.

## 2. What the model does, and what it is not allowed to do

| Step | Model? | Output |
|------|--------|--------|
| Domain guard | only when the heuristics are inconclusive | in/out of domain |
| Rewrite + intent | yes, structured | `ExtractedIntent` (Pydantic) |
| Entity resolution | **no** | ids checked against the MES |
| Tool selection | model proposes, template guarantees, registry validates | ordered plan |

The model classifies and phrases. It never states a factory value, never sees a
table, and cannot introduce a tool: `ExtractedIntent.required_tools` is filtered
against the registry, and anything unrecognised is dropped and recorded in
`notes` — the architecture's "unknown tool name → step dropped, logged".

## 3. Four decisions worth stating

**Rewrite and intent come from one call.** The original sketch had two. Split,
they can disagree — and a rewrite that contradicts the intent derived from it is
worse than no rewrite. One structured object makes disagreement impossible.

**Tool selection is model-proposed and template-guaranteed.** The model is given
the live tool catalogue and names the tools it needs. A per-intent template then
guarantees the floor: the sequence each demo scenario depends on is always
present, in an order where each step's inputs exist. Extra tools the model asks
for, and the registry recognises, are appended.

This is ADR-1's reasoning applied one level down. A purely model-chosen plan
varies run to run — unacceptable in front of a factory manager, and untestable
against the fixed sequences in [`04-demo-scenarios.md`](04-demo-scenarios.md). A
purely fixed plan would not be an agent. The split keeps the model doing the
part that needs judgement while the demo stays reproducible.

**The guard fails closed.** Deny phrases with no in-domain signal are settled
without a model call; factory vocabulary or an entity id is accepted outright.
Anything else asks the model — and if none is available, the request is
**rejected**. Turning away the occasional legitimate question is the right trade
for a system that must never answer an off-topic request in a demo.

Note the ordering: a denial only stands when *nothing* in the sentence is
industrial. "Write me a story" is refused; "Write a report on CNC-03 downtime"
is not.

**Arguments that depend on earlier steps are declared, not resolved.** Step 2
needs the machine type that step 1 will return, so the plan carries a binding
(`machine_type ← step 1 · data.part.required_machine_type`) instead of a value.
The plan stays fully inspectable before anything executes, and the executor has
nothing to re-derive.

## 4. Intents

| Intent | Scenario | Planned tools |
|--------|----------|---------------|
| `production_capacity` | S1 hero | part info → available machines → maintenance → inventory → **calculate** |
| `machine_health` | S2 | machine status → maintenance |
| `bottleneck` | S3 | part info → available machines → maintenance → calculate |
| `production_analysis` | S4 | history → orders → maintenance (incl. completed) |
| `maintenance_attention` | S5 | machine status (all) → maintenance |
| `machine_status` | Demo 1 | machine status |
| `production_orders` | — | orders |
| `material_inventory` | — | inventory |
| `unknown` | — | none; always a clarification |

`metric` carries the axis scenario R2 turns on: `max_capacity`,
`planned_production`, `actual_production`. A quantity question naming neither a
period nor a metric is ambiguous, because capacity, plan and actual are three
different numbers and picking one silently is the failure this prototype exists
to prevent. A *planned quantity* question is routed to `production_orders`, not
to the capacity engine — that number is recorded, not calculated.

## 5. Entity resolution is grounded in the factory

Extraction proposes ids; the repository checks them. `CNC-09` comes back
`exists: false` alongside the machines that do exist, which is what scenario R5
needs. Informal forms are normalised — `cnc 3`, `CNC3`, `cnc-03` all resolve to
`CNC-03`.

An unknown entity does **not** stop the plan. The reply that "CNC-09 does not
exist" is then sourced from a tool result rather than asserted by the agent,
which is the same discipline the rest of the system follows.

## 6. Provider abstraction — local-first (ADR-5)

The factory's production environment is isolated, so the prototype runs a
**locally deployed open-weight model** by default. Factory questions and MES data
never leave the application environment.

| Provider | Role |
|----------|------|
| **`openai_compatible`** | **Primary.** A local model behind Ollama / vLLM / llama.cpp |
| `anthropic` | Optional development reference; an extra dependency, not part of the delivered architecture |
| *(none)* | Deterministic rule-based understanding |

`LLMClient` exposes exactly two operations, `structured()` and `complete()`.
Switching providers is one line of `.env`; no code above the interface changes.

### Structured output is the binding constraint, not model size

Every LLM step extracts into a Pydantic model, so a model that writes fluent
prose but returns malformed JSON one time in five is unusable, while a smaller
model that always returns valid JSON is fine. Local serving stacks vary — some
accept a full `json_schema`, some only "must be JSON", some neither — and a
7B–14B model will occasionally wrap its answer in a code fence regardless.

[`openai_compatible.py`](../backend/app/llm/openai_compatible.py) therefore
negotiates and repairs:

1. `response_format: json_schema` — strict, the server enforces the shape
2. `response_format: json_object` — server guarantees JSON, schema goes in the prompt
3. prompt-only — schema and instruction in the system prompt

It settles on the best mode the endpoint accepts and remembers it. JSON is
recovered from code fences or surrounding prose. If a reply still fails
validation, the validation error is sent back once with a request to correct it.
Only then does it raise — and the agent falls back to rules.

`temperature` is set to **0** here: local runtimes accept it and a small model is
markedly more consistent with it. (Current hosted Claude models reject the
parameter, which is why it lives only on this provider.)

### Verify before you trust it

```bash
make llm-check                                      # the full check
make llm-check ARGS="--model qwen2.5:7b-instruct"   # try another model
```

It reports reachability, the negotiated mode, the schema-valid rate, the intent
match rate against the five scenarios and all fifteen phrasing variants, the
repair rate, and latency — then gives a READY / MARGINAL / NOT READY verdict and
the `LLM_STRUCTURED_MODE` value to pin. Run it before the demo, on the machine
that will run the demo.

### Measured against a real endpoint

Ollama 0.33.3 on 4 CPU cores, no GPU. Twenty-one cases: the five demo scenarios,
Demo 1, and all fifteen phrasing variants.

| | `qwen2.5:3b` | `qwen2.5:7b` |
|---|---|---|
| Structured mode negotiated | **`json_schema`** | **`json_schema`** |
| Schema-valid replies | **21/21**, zero repairs | **21/21**, zero repairs |
| Intent match | 19/21 | **21/21** |
| Entity ids — delivered *(model alone)* | **21/21** *(4/21)* | **21/21** *(—)* |
| Rewrites usable — delivered *(model alone)* | **21/21** *(14/21)* | **21/21** *(—)* |
| Latency per call | median 8–18 s | median 37 s |

**Ollama accepts `json_schema` natively**, so the strictest mode is the one in
use and the fallbacks never fire. Structured output was never the problem.

Four findings changed the code.

**Prompt beat model size, by a wide margin.** The first run of the same 3B model
matched **6 of 21** intents. The JSON was already perfect; the model simply did
not know what `machine_health` covered as opposed to `machine_status`, because a
JSON schema carries only the enum's *names*. Adding an explicit intent guide —
what each intent means, and the distinctions that are actually confusable — took
the same model from **29% to 90%** with no change of model. This is why
`INTENT_GUIDE` lives in [`extractor.py`](../backend/app/agent/extractor.py)
rather than being left implicit in the enum.

**Cold start had to move out of the first request.** A 7B model's first three
calls failed outright: loading the model into memory, plus compiling a grammar
for the schema the first time the server sees it, exceeded the request timeout.
That one-off cost is 15–78 s for 3B and minutes for 7B. In a demo it would have
landed on the factory manager's first question. The app now runs one real
structured extraction at startup, and `LLM_TIMEOUT_S` defaults to 180 s.

**A small model is unreliable at literal extraction, and deterministic code is
not.** Running the real API surfaced what the offline check had missed: the 3B
model returned the right *intent* for "How many A12 parts can we produce this
week?" and an **empty `part_ids`** — turning an answerable question into "which
part do you mean?". It also placed "Why was A12 production lower **yesterday**?"
in *this week*, which would have silently answered the wrong question, and
quietly assumed a period for a bare "How many A12?" instead of clarifying.

None of these need a bigger model. A part code, a machine id and the word
"yesterday" are literal tokens, and a regex reads them more reliably than a
language model infers them. So the pipeline applies **deterministic floors** over
the model's reading, in `_sanitise()`:

| Floor | Why |
|---|---|
| Entity ids are **unioned** with a pattern match | The model's findings are kept and added to, never replaced |
| A **stated** time expression overrides the model's window | A wrong window silently changes every number downstream |
| The R2 ambiguity rule can only **add** caution | A model that quietly picks one of three different answers is the failure this prototype exists to prevent |
| A degenerate rewrite is replaced | Small models echo the intent label or truncate; the rewrite is shown to the user |
| **Two confusable intents are settled by a literal signal** | The live scenario matrix found "Max A12 quantity by Sunday?" read as *production orders* and "Which CNC looks unhealthy?" as a *status* lookup — each ran the wrong tools and produced no figure. "Max/capacity/potential" with no planning word is capacity; "which…" naming no machine is maintenance attention. Acts only where the rules reading agrees, so it corrects a known confusion rather than the model in general |

The measured effect: entity extraction went from **4/21 to 21/21 delivered** on
the 3B model. The model does the semantics; code does the literals.

**Both models embellished in plain completion**, and neither invented the
figures it was given. Asked to explain a capacity result, the 3B model kept
`3,325` and `CNC-03` exactly — then added "there are 28 hours remaining", a
number nobody supplied. The 7B model did the same. That is precisely the failure
the validator catches: numbers must be *grounded in tool output*, not merely
plausible. It also catches the failure this experiment did **not** predict — a
number that is in the data and still the wrong answer. See
[`10-reliability.md`](10-reliability.md) §4.

**Cold start belongs at startup, not in the first question.** Warming now runs in
the **background** with its own budget (`llm_warmup_timeout_s`, 900 s), so the API
is usable immediately — on rules until the model is ready, then on the model.

### The fallback is an architecture feature, not a stopgap

```
                    ┌─ Local LLM path
Question ───────────┤
                    └─ Deterministic fallback
                              ↓
                       Controlled tools
                              ↓
                       Factory calculations
```

With no model reachable — none configured, endpoint down, or a mid-request
failure — the agent falls back to rule-based understanding and labels every
response (`understood_by: "rules"`, `degraded: true`, `provider: "none"`), with
the reason in `notes`. The endpoint is probed once at startup, so a configured
but unreachable model costs no per-request timeout.

The point to make to the factory manager: **even when the model fails to
interpret a request, it cannot corrupt a factory calculation or reach the
database.** The deterministic application layer stays in control. That is a
stronger claim than "we use an LLM".

### Latency: almost all of it is the prompt, and it is cacheable

Measured with Ollama's native timings, which separate prompt evaluation from
generation. The system prompt is ~1,360 tokens (tool catalogue + intent guide).

| | `qwen2.5:3b` | `qwen2.5:7b` |
|---|---|---|
| **Cold call** | **78 s** | **167 s** |
| — model load | 4.9 s | 10.2 s |
| — prompt evaluation | **63.2 s** | **135.1 s** |
| — generation | 9.8 s | 21.3 s |
| **Warm call** | **7.4 s** | **20.1 s** |
| — prompt evaluation | 1.2 s | 2.5 s |

Prompt evaluation is **81% of the cold cost**, and the prompt prefix is identical
on every call, so the server caches it: 63.2 s → 1.2 s, a 50× drop, on every call
after the first. Cache hits were 4/4 on both models.

The catch is that Ollama unloads an idle model after five minutes and discards
that cache with it — a measured **79 s** stall on the next question, which in a
demo lands on the first question after a quiet moment. Two settings remove it
entirely:

- `OLLAMA_KEEP_ALIVE=-1` on the model server (set in `docker-compose.yml`), which
  pins the model and its cache in memory;
- the background `warm_up()` at startup, which pays the cold cost once at deploy.

Verified: after **6.7 minutes idle**, a call returned in **6.1 s** — model load
0.0 s, prompt evaluation 1.1 s. Through the API on the composed stack, live
questions run **5.8–10.5 s**.

### Which model to run

`qwen2.5:7b-instruct` scored **21/21 on every measure** and is the recommendation
for the demo. `qwen2.5:3b-instruct` also passes as READY and is roughly four
times faster; its two intent misses are borderline phrasings. Anything in the
7B–14B instruct range should work — verify with `make llm-check` on the machine
that will run the demo.

On latency, warm and cached on 4 CPU cores with no GPU: **3B meets the ≤ 10 s
target (7.4 s); 7B does not (20.1 s)**. A GPU brings 7B well inside it, mainly by
making the one-off prompt evaluation cheap. A third option needs no GPU: run 3B
for the guard and intent extraction, where the deterministic floors already cover
its weaknesses, and 7B only for the explanation, which is a single call.

## 7. Two corrections from the current Claude API

**Sampling temperature is gone.** The initial documentation specified "LLM temperature
0" for determinism. The current models reject `temperature` outright — a request
carrying it fails. `LLM_TEMPERATURE` has been removed from configuration.
Reproducibility was never really coming from that knob: it comes from structured
extraction into a fixed schema, from templates guaranteeing the plan, and from
every number living outside the model.

**The Claude reference model is `claude-opus-5`,** replacing the
`claude-sonnet-5` placed in `.env.example` at project setup before the API reference was
consulted. It applies only to the optional development path; the delivered
default is the local model.

## 8. HTTP surface

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/understand` | question → guard, rewrite, intent, entities, plan |
| `GET` | `/api/agent` | which provider is active, the intents, the pipeline stages |

```bash
curl -s -X POST localhost:8000/api/understand \
  -H 'content-type: application/json' \
  -d '{"question":"How many A12 can we produce this week?"}'
```

```
rewritten: Calculate the maximum feasible A12 production quantity for this week
           using available CNC resources, scheduled maintenance and material stock.
intent=production_capacity  metric=max_capacity  window=2026-09-08..2026-09-13

AI Analysis Steps:
  1. Get A12 information
  2. Find eligible machines and their available hours   [machine_type <- step 1]
  3. Check scheduled maintenance
  4. Check material availability                        [material_id <- step 1]
  5. Calculate capacity and identify the constraint
```

## 9. Verification

| File | Covers |
|------|--------|
| `test_guard.py` | 24 tests — 9 factory questions accepted, 8 off-topic rejected, deny-word-in-a-real-request, fail-closed paths, no model call for clear cases |
| `test_extractor.py` | 36 tests — the 5 scenarios, all 15 phrasing variants, windows, ambiguity, dropped tool names, provider-failure fallback |
| `test_understanding.py` | 19 tests — the documented plan for each scenario, R1–R5, bindings, reproducibility |
| `test_local_llm.py` | 19 tests — mode negotiation and fallback, fenced/prose-wrapped JSON, repair round-trip, probe, unreachable endpoint, temperature |
| `test_llm.py` | 16 tests — Claude request construction, refusal handling, typed error translation, provider selection |
| `test_api.py` | +7 tests over HTTP |

**All 15 phrasing variants resolve to their base scenario's intent** on the
deterministic path alone. Asking the same question twice returns a byte-identical
reading.

## 10. What comes after understanding

Executing the plan — bindings resolved from earlier results, a refusal when a
required field is missing, steps streamed as they complete, and the whole trace
written to `agent_run_log` — is documented in
[`08-multi-step-execution.md`](08-multi-step-execution.md).

The explainer calls `complete()` on the **same local model**, so the final
natural-language answer is generated inside the factory environment too — while
the numbers in it still come from Python. That separation is the strongest
single point in the demo.
