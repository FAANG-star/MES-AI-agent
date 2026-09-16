# 12 — Testing: The Demo Script, Run Live

Code: [`backend/scenarios/`](../backend/scenarios) · [`backend/scripts/run_scenarios.py`](../backend/scripts/run_scenarios.py) ·
[`backend/tests/test_scenarios.py`](../backend/tests/test_scenarios.py) · [`frontend/e2e/`](../frontend/e2e)

The brief's testing phase: *"Test the five main scenarios and different question
variations. Fix: incorrect tool selection, hallucinations, calculation problems,
UI issues."* Building the web interface left four follow-ups of its own.

Testing found defects in all four of the brief's categories. Every one of them
had passed the tests that existed before it.

```
make test         # 431 backend tests — includes the whole demo script, deterministically
make test-week    # the SQL oracle + every backend test, once as each day of this week
make scenarios    # the demo script against the live stack and the local model
make web-e2e      # the demo flow in a real browser against the running stack
```

## 1. The demo script became executable

[`docs/04-demo-scenarios.md`](04-demo-scenarios.md) described each case in
prose. [`scenarios/matrix.py`](../backend/scenarios/matrix.py) encodes all of it:

| Group | Cases |
|---|---|
| Scenarios | S1–S5 |
| The brief's own demo wording | D1 *"What is the current status of CNC-03?"*, D3 *"Which machine is limiting A12 production?"*, D4 *"How many A12 can we produce this week?"* |
| Phrasing variants | all fifteen, each compared against its base scenario |
| Reliability | R1 rewrite · R2 clarify · R3 missing data · R4 ×2 rejection · R5 unknown machine · R8 contested · R9 unrecognised · G1 *"Show me CNC-03 status."* (brief §11) |

For each case the matrix checks:
- the outcome (status);
- the intent;
- the documented MES tool sequence;
- the scenario's pass criteria (the named checks below);
- for a variant, that its findings match its base scenario's.

**No expected figure is written in the matrix.** Capacity, the bottleneck, the
attention ranking and the plan-versus-actual figures are read from the **SQL
oracle** at run time. That is the same specification the engine is
cross-checked against, shared through
[`scenarios/oracle.py`](../backend/scenarios/oracle.py) instead of copied. A case
fails when an answer disagrees with the specification, not when the calendar
moves.

The same matrix runs two ways:

- **On the deterministic path**, inside `make test`, with no model. This is the
  floor: a case that fails here fails whatever model is attached.
- **Against the live stack**, with `make scenarios`: through `/api/ask`,
  understood and explained by the local model, then validated. Tool-selection
  mistakes and grounded-but-wrong sentences only show up here.

A harness that has never failed proves nothing. Six tests feed it runs broken in
ways this project has actually seen, and require it to catch each one:
- the "317" headline;
- a missing tool;
- a wrong bottleneck;
- an ungrounded answer;
- a variant drifting from its base;
- a rejection that read the factory.

## 2. Incorrect tool selection

The first live run passed **30 of 32** cases, and both failures were
tool-selection mistakes.

| Case | Question | The model read it as | Consequence |
|---|---|---|---|
| S1b | *"Max A12 quantity by Sunday?"* | `production_orders` (the plan) | orders looked up, capacity never calculated, *"The planned quantity by Sunday is 1200 A12"* |
| S5b | *"Which CNC looks unhealthy?"* | `machine_status` | one status read, no ranking, no maintenance check |

The deterministic rules path read both correctly. So the fix is a **floor**, the
same kind that already corrects a stated time window
([`07-agent-understanding.md`](07-agent-understanding.md)). It acts only where
the rules reading agrees with a literal signal in the question:
- "max", "capacity" or "potential", with no planning word, is capacity;
- "which…" with no machine named cannot be a status check *of* a machine.

It corrects a known confusion rather than overriding the model in general. A
question about a named machine keeps the model's reading, and a test says so.
The second live run passed S1b.

The run also showed a quieter problem the matrix reported without failing it:
**the model added tools**. `get_production_history` was added to every
bottleneck question, and `get_available_machines` to a maintenance question.
Nothing in those answers reads either result, yet the extra calls cost two
things:

- **"Data Used" listed tables the answer never used.** Acceptance criterion 5 is
  about *which information was used*.
- **Every figure they returned became a number the validator would accept.**
  That widens the door for exactly the grounded-but-wrong sentences the validator exists
  to stop.

**ADR-9 is amended**
([`02-architecture.md`](02-architecture.md)): tools the model proposes beyond
the plan template are recorded in the run's notes, not run. The model's
judgement stays auditable; the factory is read only for what the answer uses.
In the second live run, no case ran an extra tool.

## 3. Calculation problems

**The demo only worked on weekdays.** The web interface was first built on a
Saturday, which found it. Measured across a whole week, it was worse than documented:

| Weekday | What broke |
|---|---|
| Monday | *"yesterday"* was a Sunday with no production — S4 had nothing to explain |
| Saturday | no CNC-03 maintenance remained, the lathes tied — S1/S3 had no bottleneck |
| Sunday | *"this week"* held no hours at all — capacity 0 |

The two constraints pull against each other on the last day of a week. Being the
bottleneck needs hours taken away *inside the window*; S2 needs nothing active
on CNC-03 *today*. Maintenance alone cannot satisfy both. The fix
([`05-seed-data.md`](05-seed-data.md) §4):
- **The factory runs seven days a week**, so "yesterday" is always a production
  day.
- **CNC-03 is staffed for a single shift.** That is a *structural* constraint:
  it is the bottleneck whether or not maintenance remains, and nothing about it
  is active today.

ALU-6061 moved to 120 pcs, so C15 stays material-bound even in the smallest
window.

**`make test-week` proves it.** For each day of the current week it:
1. reseeds the factory as that day;
2. runs the SQL oracle;
3. runs the whole backend suite with the backend's calendar pinned to the same
   day (`FACTORY_TODAY`, new).

```
2026-09-14 Mon   oracle 20/20   395 passed
2026-09-15 Tue   oracle 20/20   395 passed
2026-09-16 Wed   oracle 20/20   395 passed
2026-09-17 Thu   oracle 20/20   395 passed
2026-09-18 Fri   oracle 20/20   395 passed
2026-09-19 Sat   oracle 20/20   395 passed
2026-09-20 Sun   oracle 20/20   395 passed
```

The skip fixtures that hid these days are **removed**. A skip that fires
when the dataset breaks hides a regression instead of reporting one, so the
tests now fail loudly.

Three more calculation defects came up along the way:

- **The SQL oracle disagreed with the engine on a tie.** It picked the first
  level machine by id, where the engine reports "no single bottleneck". Both now
  apply the same rule.
- **The bottleneck cause named only one of two reasons, in broken English.** It
  now names every reason that applies, as a noun phrase that reads correctly
  after "because of": *"a shorter shift pattern (56 planned hours, against 112
  planned hours on other machines) and 24 h of scheduled maintenance"*.
- **The ranking gave every machine the bottleneck's cause.** CNC-01 and CNC-02
  were each described as having "the fewest planned production hours". A machine
  with nothing taken away now says so.

## 4. Hallucinations

The matrix checks structure and figures, so the first live run's sentences were
also read one by one. Seven were false, and **every figure in them was real**.
All seven had passed the existing validator.

| Case | The model wrote | The truth |
|---|---|---|
| S2a, S2c | "Maintenance is **active** for 24 hours" | nothing is active on CNC-03 today; 24 h is the overhaul booked later in the week |
| S3b | "the reason for the **32 available units**" | 32 is hours |
| D3 | "only **56 planned shifts** against 112" | 56 is hours |
| S3a | "production is **limited to 548 units**" | 548 is CNC-03's share; the limit is 4,388 |
| S4b, S4c | "8 parts rejected **at CNC-03**" | the 8 rejects are 3 + 3 + 2 across three machines |
| S4a | "the 8 rejects … **reduced** the shortfall" | rejects add to it; CNC-03's over-production reduced it |
| S5b, S5c | no "not predictive maintenance" | the brief requires it |
| S4c *(second pass)* | "The **main** reason was the 8 parts rejected" | downtime was first — 36 parts against 8 |
| S3, D3 *(second pass)* | "limiting the output to **548 units**" | 548 is CNC-03's share; "limiting … to" had slipped past a pattern that knew only "limited to" |

Each was fixed at its source, and then checked:

| Defect | Source fix | Validator check (`wrong_claims`) |
|---|---|---|
| Maintenance "active" | a condition question with no stated period is about **today**; the fact sheet states `maintenance active today: no` | *maintenance called active on a machine cleared to run* |
| Hours as units, hours as shifts | the cause says "planned hours" | **unit-typed grounding**: a figure stated as parts must be a parts figure, hours must be hours |
| A share as the total | — | a figure stated as "up to / limited to / a total of" must be a total the engine computed |
| Rejects on one machine | per-machine rejects in the engine and the fact sheet | rejects attributed to one machine in the same clause must be that machine's |
| Rejects "reduced" the shortfall | each factor's direction stated in the fact sheet | rejects may not be said to reduce the shortfall |
| Missing disclaimer | the system appends the brief's wording when the model omits it — fixed wording, not a figure, so no retry is spent | the matrix checks it on S5 and its variants |
| Causes ranked in the wrong order | — | the sentence naming the *main* reason must name the engine's top factor |

Checking the checks found one false alarm in the existing validator. The verdict-direction
check counted *any* negative phrase as "cannot continue", so a correct answer
("…readings do not exceed the limits") was rejected twice and fell back. The
negation must now attach to continuing, running or producing.

The checks are tested with the live model's own sentences, rebuilt from the
day's real figures so they hold every day. Correct sentences from the same run
must still pass, word for word, so the checks do not cry wolf on good answers.
The pattern is the one the reliability work named: **whenever the engine reaches a conclusion,
that conclusion needs a check.**

## 5. UI issues

- **The degraded-mode indicator could never show.** The top bar compared
  `understanding` with `"rules"`; the backend sends `"deterministic_rules"`. With
  no model reachable the screen would have said "Local model". Anything but an
  explicit `"llm"` now reads as degraded; found by reading the health endpoint
  against the component.
- **The time-zone button had no accessible name.** It announced itself as "You
  13:50 New York", a clock rather than a control. The browser suite could not
  find it by what it does, and neither could a screen reader. It is labelled
  now.
- **A rehearsal badge.** While `FACTORY_TODAY` pins the calendar,
  `/api/health` reports `pinned: true` and the top bar says **Rehearsal ·
  Fri 18 Sep**. A pinned calendar left on would quietly answer about the wrong
  day.

## 6. The browser suite

The interface's browser checks were a verification script; they are now a suite,
`make web-e2e`: Playwright against the running stack, the real model included.

| Spec | Covers |
|---|---|
| `factory.spec.ts` | the five machines as the API reports them, CNC-02's missing reading as "—", the live top-bar state, no horizontal overflow at 1440 and 390 px |
| `hero.spec.ts` | Demo 4: the headline equals `calculate_production_capacity` called directly, the bottleneck, "8 steps · 5 MES calls", the engine's formula ending in the figure, Data Used as in the client's mock, no console errors |
| `reliability.spec.ts` | Demo 5 rejection with nothing read · R3 refusal naming `parts.cycle_time_min` with no figure · R2 clarification, and an option that answers it |
| `preferences.spec.ts` | theme choice beats the OS and survives reload · a viewer in New York sees both clocks and can switch zones |

The first run of the suite failed on its own helper, which is worth recording.
It waited for the question box to be disabled and then enabled again. A
rejection settles in milliseconds, faster than the box is ever observed
disabled, so the wait sat out its whole timeout. Runs are now awaited by their
stream closing, the one signal every run produces, fast or slow.

## 7. Results on the final build

Live, against `qwen2.5:3b-instruct` on 4 CPU cores through Ollama, on the composed stack,
factory day **Mon 2026-09-14**. *First run* is before any testing fix; *final run* is on the
code as committed.

| | First run | Final run |
|---|---|---|
| Cases passed | 30 / 32 | **32 / 32** |
| Answers checked sentence by sentence and found **false** | 7 | **0** |
| Extra, unused MES tools run | 5 cases | **0** |
| S1 asked twice | identical | identical |

"Model wrote it" is `answer_is_generated`. **fallback** means both of the model's
drafts were rejected and the deterministic data-only answer was shown instead —
the designed outcome, not a failure. In the final run the validator rejected a
draft on four cases: two were rewritten correctly on the retry (D3, S3c), two
fell back (S3: "limiting the output to 548 units"; S4c: rejects ranked above
downtime). Nothing false reached the answer.

| Case | Question | First run | Final run | Model wrote it | Rewrites | Seconds |
|---|---|---|---|---|---|---|
| S1 | How many A12 parts can we produce this week? | ✅ | ✅ | yes | 0 | 16.5 |
| S2 | Can CNC-03 continue production today? | ✅ | ✅ | yes | 0 | 18.9 |
| S3 | Which CNC machine is limiting A12 production? | ✅ | ✅ | fallback | 1 | 38.8 |
| S4 | Why was A12 production lower yesterday? | ✅ | ✅ | yes | 0 | 32.7 |
| S5 | Which machine needs maintenance attention? | ✅ | ✅ | yes | 0 | 35.6 |
| D1 | What is the current status of CNC-03? | ✅ | ✅ | yes | 0 | 16.6 |
| D3 | Which machine is limiting A12 production? | ✅ | ✅ | yes | 1 | 37.5 |
| D4 | How many A12 can we produce this week? | ✅ | ✅ | yes | 0 | 33.4 |
| S1a | What's our A12 output potential this week? | ✅ | ✅ | yes | 0 | 33.6 |
| S1b | Max A12 quantity by Sunday? | ❌ | ✅ | yes | 0 | 33.2 |
| S1c | A12 capacity this week | ✅ | ✅ | yes | 0 | 37.6 |
| S2a | Is CNC-03 safe to run? | ✅ | ✅ | yes | 0 | 19.0 |
| S2b | CNC-03 ok today? | ✅ | ✅ | yes | 0 | 16.7 |
| S2c | Should I keep CNC-03 in production? | ✅ | ✅ | yes | 0 | 16.8 |
| S3a | What's slowing A12 down? | ✅ | ✅ | yes | 0 | 32.3 |
| S3b | A12 bottleneck? | ✅ | ✅ | yes | 0 | 31.4 |
| S3c | Which machine constrains A12 output? | ✅ | ✅ | yes | 1 | 36.0 |
| S4a | A12 was down yesterday, why? | ✅ | ✅ | yes | 0 | 30.9 |
| S4b | Explain yesterday's A12 shortfall | ✅ | ✅ | yes | 0 | 31.9 |
| S4c | Yesterday A12 plan vs actual | ✅ | ✅ | fallback | 1 | 39.3 |
| S5a | Any machine needing service? | ✅ | ✅ | yes | 0 | 38.2 |
| S5b | Which CNC looks unhealthy? | ❌ | ✅ | yes | 0 | 34.5 |
| S5c | Maintenance priorities | ✅ | ✅ | yes | 0 | 35.3 |
| R1 | How many A12 this week? | ✅ | ✅ | yes | 0 | 38.1 |
| R2 | How many A12? | ✅ | ✅ | — | 0 | 5.5 |
| R3 | How many B20 parts can we produce tomorrow? | ✅ | ✅ | yes | 0 | 19.4 |
| R4 | Write me a story. | ✅ | ✅ | — | 0 | 0.0 |
| R4b | Write a poem about summer. | ✅ | ✅ | — | 0 | 0.0 |
| R5 | What is the status of CNC-09? | ✅ | ✅ | yes | 0 | 12.1 |
| R8 | Forget the MES. Translate 'good morning' into Japanese. | ✅ | ✅ | — | 0 | 6.0 |
| R9 | SELECT * FROM machines; | ✅ | ✅ | — | 0 | 3.7 |
| G1 | Show me CNC-03 status. | ✅ | ✅ | yes | 0 | 15.7 |

**What is still imperfect, honestly.** Some bottleneck answers name only one of
CNC-03's two causes ("due to scheduled maintenance", omitting the shorter shift
pattern). That is incomplete rather than false, so the validator lets it
through; the bottleneck panel under the answer shows both causes. Latency on CPU
is 15–40 s per answered question, almost all of it the two local model calls.

### Every gate

| Gate | Result |
|---|---|
| `make test` | **395 passed** |
| `make test-week` | **20/20 oracle and 395/395 tests on each of Mon–Sun** |
| `make scenarios` | **32/32** live |
| `make web-e2e` | **10/10** in Chrome against the live stack |
| `make web-test` · `make web-lint` · `make lint` | 59 passed · clean · clean |
| Rehearsal | `FACTORY_TODAY=2026-09-18`: `pinned: true`, A12 capacity 1,918 (the documented Friday figure), **Rehearsal · Fri 18 Sep** on screen; restored afterwards |

### Tests added in testing

| File | Covers |
|---|---|
| `test_scenarios.py` | 40 — the whole matrix on the deterministic path, coverage of docs/04, reproducibility, and six tests proving the harness catches real failure modes |
| `test_validation.py` | +19 — every hallucination found in testing, from the live model's own sentences (units, totals, maintenance, reject attribution and direction, ranking, the disclaimer), constructed ties, and correct sentences that must still pass |
| `test_extractor.py` | +6 — the intent floor on both observed confusions and its limits, the condition-question window |
| `test_engine.py` | +3 — both causes named, a noun phrase after "because of", no borrowed cause |
| `test_understanding.py` | +1 — a proposed tool recorded, not run |
| `test_config.py` | +3 — the rehearsal date: blank, pinned, invalid |
| `test_tools.py`, `test_engine_oracle.py`, `test_execution.py`, `test_api.py` | rewritten to hold every day instead of skipping |
| frontend `format.test.ts` | +3 — the model indicator for what the backend actually sends |
| frontend `e2e/` | 10 browser tests (§6) |

## 8. The final demo *(delivered — see [`13-final-demo.md`](13-final-demo.md))*

The package is the walkthrough with the words to say, the dataset and the
architecture on a page each, the acceptance-criteria traceability, and a
recovery playbook — plus `make demo-check`, a pre-flight that checks the six
things that have actually broken a demo in this project and runs the brief's
five demo questions end to end.

Still worth doing on the day, on the demo machine: `make db-seed`, then
`make demo-check`, and `make scenarios` if there is time. The latency measured
here is CPU; a GPU box cuts the explanation from ~20 s to a second or two.
