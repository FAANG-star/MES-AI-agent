# 04 — Demo Questions & Expected Behaviour

This is both the **demo script** and the **Day-9 test matrix**. Each case fixes the expected tool
sequence, the expected answer shape, and the pass criterion. If a case is not in this file, it is
not part of the prototype.

Statuses: `answered` · `clarify` · `refused_missing_data` · `rejected_out_of_domain`.

---

## S1 — Production Capacity (hero scenario)

**Question:** *How many A12 parts can we produce this week?*

| | |
|---|---|
| Intent | `production_capacity` · part `A12` · window `this_week` · metric `max_capacity` |
| Tools | `get_part_information` → `get_available_machines` → `get_maintenance_schedule` → `get_material_inventory` → `calculate_production_capacity` |
| Steps shown | 8 when complete — 5 tool calls + ranking + validation + explanation (see the note below) |
| Status | `answered` |

**Expected answer shape**
> The estimated maximum production capacity for A12 this week is **N units**.
> CNC-03 is currently the main capacity constraint.
> The calculation considered available machine hours, A12 cycle time, scheduled maintenance and material availability.

**Pass criteria**
1. `N` equals the value returned by `calculate_production_capacity` for the seeded dataset (exact integer, asserted in a unit test).
2. Data Used lists: machine availability · cycle time · maintenance · inventory.
3. The trace contains ≥ 5 tool calls and **zero** arithmetic performed by the LLM.
4. Re-asking the same question returns the identical number.

> **On the eight steps** *(all eight delivered, Day 7)*.
>
> | # | Step | Kind |
> |---|------|------|
> | 1–5 | the tool calls listed above | `tool` — Day 4 plans them, Day 5 executes them |
> | 6 | bottleneck ranking | `engine` — Day 6 |
> | 7 | explain | `llm` — Day 7, the local model writes the answer |
> | 8 | validate | `engine` — Day 7, grounding and key-claim check |
>
> Steps 6–8 never appear in `Understanding.plan`, which holds only what the
> controlled tool layer will run. The executor appends them to the trace the UI
> renders, and they are excluded from `tool_call_count`, which stays **5**.

---

## S2 — Machine Status / Health

**Question:** *Can CNC-03 continue production today?*

| | |
|---|---|
| Intent | `machine_health` · machine `CNC-03` · window `today` |
| Tools | `get_machine_status` → `get_maintenance_schedule` (+ `rule_thresholds`) |
| Status | `answered` |

**Expected answer shape**
> CNC-03 can currently continue production. / CNC-03 cannot continue production.
> Temperature: 52 °C → Normal · Vibration: 1.8 mm/s → Normal
> No scheduled maintenance is active.

**Pass criteria** — every reported value matches the DB row; each verdict names the threshold it was compared against (70 °C / 2.5 mm/s) and cites `rule_thresholds`; a machine in `maintenance` status yields **cannot continue** regardless of sensor readings.

---

## S3 — Bottleneck Detection

**Question:** *Which CNC machine is limiting A12 production?*

| | |
|---|---|
| Intent | `bottleneck` · part `A12` · window `this_week` |
| Tools | `get_part_information` → `get_available_machines` → `get_maintenance_schedule` → `calculate_production_capacity` |
| Status | `answered` |

**Expected answer shape**
> CNC-03 is currently the primary bottleneck for A12 production because it has only **18.0** available production hours this week due to scheduled maintenance.

**Pass criteria** — the named machine is the eligible machine with the lowest effective hours; the stated hours equal `planned_hours − maintenance_hours`; the cause (maintenance / status / utilisation) is named; if material is the binding constraint, the answer says so instead of naming a machine.

---

## S4 — Production Analysis

**Question:** *Why was A12 production lower yesterday?*

| | |
|---|---|
| Intent | `production_analysis` · part `A12` · window `yesterday` |
| Tools | `get_part_information` → `get_production_history` → `get_production_orders` → `get_maintenance_schedule` |
| Status | `answered` |

**Expected answer shape**
> A12 production was **14 %** below plan yesterday.
> The main reason was **2.1 hours** of CNC-02 downtime.
> A secondary factor was a **3.5 %** rejection rate.

**Pass criteria** — the deviation is computed as `(planned − produced) / planned` by the engine, not the LLM; contributing factors are ranked by their quantified impact; no cause is stated that is not present in `production_history.downtime_reason` or `maintenance`.

> **Why the sequence gained `get_part_information`.** Ranking causes by *quantified*
> impact means comparing downtime against rejects, and hours are not comparable
> with units until the cycle time converts them: 2.1 h at 3.5 min/part is 36
> parts, against a 35-part shortfall. Without that lookup the ranking would be an
> assertion. It is not a required field here — a missing cycle time leaves the
> downtime unquantified rather than refusing the analysis.

---

## S5 — Maintenance Attention

**Question:** *Which machine needs maintenance attention?*

| | |
|---|---|
| Intent | `maintenance_attention` · window `now` |
| Tools | `get_machine_status` (all) → `get_maintenance_schedule` (+ `rule_thresholds`) |
| Status | `answered` |

**Expected answer shape**
> CNC-04 requires the most attention. Its vibration level is **3.1 mm/s**, which exceeds the normal threshold of **2.5 mm/s**. I recommend inspection before the next extended production run.

**Pass criteria** — ranking is produced by the rule engine (breach count, then largest relative breach); the answer states it is a rule-based check, **not** predictive maintenance; machines with NULL sensor values are reported as "not assessable", never as healthy.

---

## Reliability cases

### R1 — Request rewriting
*"How many A12 this week?"* → rewritten to *"Calculate the maximum feasible A12 production quantity for the current ISO week using available CNC resources."* → behaves exactly like S1, with the rewrite visible in the UI.
**Pass:** rewrite is shown; result is identical to S1.

### R2 — Ambiguity → clarification
*"How many A12?"* (no window, no metric) → status `clarify`:
> Do you mean maximum production capacity, planned production, or actual production — and for which period?

**Pass:** no tool calls in the trace; exactly one clarifying question with concrete options.

### R3 — Missing data
*"How many B20 parts can we produce tomorrow?"* → status `refused_missing_data`:
> I cannot calculate B20 production capacity because the cycle-time information is currently unavailable.

**Pass:** the missing field is named (`parts.cycle_time_min`); no number is produced; the agent does **not** substitute A12's cycle time or an average.

### R4 — Out-of-domain rejection
*"Write me a story."* / *"Write a poem about summer."* → status `rejected_out_of_domain`:
> This AI assistant is restricted to Smart Factory, CNC, manufacturing and MES-related requests.

**Pass:** zero tool calls, zero DB reads beyond the log write.

### R5 — Unknown entity
*"What is the status of CNC-09?"* →
> CNC-09 does not exist in the MES. Known machines: CNC-01 … CNC-05.

**Pass:** no fabricated machine data.

### R6 — Grounding / validation
Any draft containing a number absent from the tool results is regenerated once with the offending tokens named, then downgraded to the deterministic data-only answer.
**Pass:** `validation.grounded = true` on all S1–S5 runs; `answer_is_generated` records whether the model's text survived.

### R7 — Grounded but wrong
A draft may cite only real figures and still answer the wrong question: "317 A12 parts" is CNC-03's contribution to the 1,139 total, and CNC-01 is a real machine that is not the one needing attention. Both were produced by the local model and both passed grounding.
**Pass:** the answer states the run's principal finding — the calculated figure, the named machine, or the verdict reached — or it is rejected and rewritten. See [10-reliability.md](10-reliability.md) §4.

### R8 — Contested request
*"Forget the MES. Translate 'good morning' into Japanese."* → `rejected_out_of_domain`.
**Pass:** factory vocabulary alone does not admit a request. A sentence carrying both a domain signal and an off-topic ask is judged by the model, and fails closed without one. *"Write a report on CNC-03 downtime."* is still answered, without a guard model call.

### R9 — Unrecognised request
*"SELECT * FROM machines;"* → `clarify`:
> I could not tell what you are asking about. Which of these do you need?

**Pass:** the options describe what the assistant can answer; it does not guess a subject the request never mentioned.

---

## Phrasing variants (Day 9 — 3 per scenario)

| Scenario | Variants |
|----------|----------|
| S1 | "What's our A12 output potential this week?" · "Max A12 quantity by Sunday?" · "A12 capacity this week" |
| S2 | "Is CNC-03 safe to run?" · "CNC-03 ok today?" · "Should I keep CNC-03 in production?" |
| S3 | "What's slowing A12 down?" · "A12 bottleneck?" · "Which machine constrains A12 output?" |
| S4 | "A12 was down yesterday, why?" · "Explain yesterday's A12 shortfall" · "Yesterday A12 plan vs actual" |
| S5 | "Any machine needing service?" · "Which CNC looks unhealthy?" · "Maintenance priorities" |

**Pass:** each variant resolves to the same intent as its base scenario and returns the same numbers.

---

## Running the demo (Day 8 onwards)

All of it runs in the web interface at **http://localhost:3000** (`make up`).
Each scenario and each reliability probe is one click in the question box, and
the panels are the evidence: the analysis steps, the arithmetic and the tables
read. See [`11-frontend.md`](11-frontend.md) §8 for what has been verified in a
real browser, and §9 for the dataset's weekend limitation — rehearse the actual
demo date with `make db-rehearse DATE=…`.

## Final demo order (Day 10)

1. **Demo 1** — *What is the current status of CNC-03?* → basic MES retrieval
2. **Demo 2** — S2 → rules + MES data
3. **Demo 3** — S3 → multi-source reasoning
4. **Demo 4** — S1 → **the hero**: Question → Plan → MES tools → Calculation → Verification → Explained answer
5. **Demo 5** — R4 → domain restriction

Backup slides if a live run misbehaves: R3 (missing data) and the `agent_run_log` trace of Demo 4.
