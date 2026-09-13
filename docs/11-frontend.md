# 11 — The Web Interface (Day 8)

Code: [`frontend/app/`](../frontend/app) · [`frontend/components/`](../frontend/components) ·
[`frontend/lib/`](../frontend/lib)
Tests: 32 frontend unit tests · backend 310 passing, 6 skipped (see §9).

Seven days of work produced a system that answers factory questions correctly.
None of it was visible. Day 8 is the screen a factory manager actually looks
at — and the screen has one job beyond showing the answer: **make the answer
checkable without taking anyone's word for it.**

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Smart CNC Factory MES Copilot      local model · DB read-only · 12:28 JST│
├──────────────────────────────────────────────────────────────────────────┤
│  FACTORY STATUS   CNC-01 running 72.5 °C ≥70 · CNC-02 — no reading · …    │
├──────────────────────────────────────────────────────────────────────────┤
│  ASK THE FACTORY  [ How many A12 parts can we produce this week? ]  [Ask] │
│  demo scenarios · reliability probes                                     │
├────────────────────────────────────┬─────────────────────────────────────┤
│  ANSWER                            │  AI ANALYSIS STEPS   5 MES tool calls│
│    Interpreted as: …               │   1 ✓ get_part_information   MES tool│
│    ESTIMATED A12 CAPACITY          │   …                                  │
│    411 units                       │   6 ✓ calculation_engine  Calculation│
│    "We can produce up to 411…"     │   7 ✓ explainer       Language model  │
│    ✓ validated · phrased by model  │   8 ✓ grounding_validator Calculation │
│  HOW THE NUMBER WAS CALCULATED     ├─────────────────────────────────────┤
│    per-machine table + the formula │  DATA USED                           │
└────────────────────────────────────┴─────────────────────────────────────┘
```

## 1. The interface makes one argument

Every panel exists to support a single claim: *the model chose which question
was being asked and how to phrase the result; it did not produce a figure.*

| Panel | What it proves |
|---|---|
| Interpreted as | FR-2 — the rewrite is shown, not hidden |
| Headline figure | The engine's number, leading the card |
| AI analysis steps | Each row labelled **MES tool** / **Calculation** / **Language model** |
| How the number was calculated | `CapacityResult.formula`, the engine's own working |
| Data used | Tables, columns, ids and row counts the tools reported |
| ✓ validated against the data | FR-7 — grounding and the key-claim check, with retries |

A viewer who distrusts the sentence can read the arithmetic under it, and then
the list of rows the arithmetic came from. That is the whole design.

## 2. The UI computes nothing

`lib/format.ts` formats; it never calculates. No component adds, divides or
compares a factory figure — the totals, percentages and rankings arrive final
and are printed as received. The one apparent exception is honest: the status
strip colours a reading red when it is at or past a threshold the MES supplied,
which is a comparison for the eye, not a verdict. Verdicts come from the rule
engine, with the limit cited.

Two small decisions follow from the same discipline:

**Digits are grouped with a fixed locale**, not the browser's. `1,139` must
read identically on the demo laptop and on the developer's machine; a figure
that renders differently in two places is exactly what this project refuses to
ship.

**The factory clock is never converted.** The backend stamps `…T12:28+09:00`;
the UI reads the hours and minutes out of that string. Parsing it into a
`Date` would re-express Tokyo's 12:28 as 03:28 for a reviewer in London and
label it the factory's time. The factory has one clock.

## 3. One origin: the browser never calls the backend

Every request goes to the Next.js server, which forwards it
([`app/api/mes/[...path]/route.ts`](../frontend/app/api/mes/[...path]/route.ts)):

```
browser ──▶ Next.js (server) ──▶ FastAPI
         /api/mes/ask/stream      http://backend:8000/api/ask/stream
```

Two reasons, one practical and one architectural:

- **It works in the composed stack.** Inside Docker the API answers to
  `http://backend:8000` — a hostname the browser cannot resolve. Proxying means
  there is no public API URL to configure and no CORS involved. The Day-1
  `NEXT_PUBLIC_API_URL` has been replaced by a server-side `MES_API_URL`.
- **The surface stays controlled**, which is the tool layer's own principle
  applied one level up: a fixed list of routes may be reached and anything else
  is a 404 at the proxy. A UI bug cannot become an unexpected backend call.

## 4. Streaming, because the model takes its time

`EventSource` cannot be used — it only issues GET requests, and the question
travels in a POST body. So the response is read as a stream and parsed by
[`lib/sse.ts`](../frontend/lib/sse.ts), which is a pure function over strings
and has eleven tests, because the failure it must survive is certain and
boring: **chunk boundaries are not event boundaries**, and an event will
eventually arrive split down the middle.

Measured through the proxy on the composed stack, warm:

```
[  0.0s] accepted
[ 10.1s] understanding   intent=production_capacity  plan=5
[ 10.1s] step 1..5   the five MES tool calls          ok
[ 10.1s] step 6      calculation_engine               ok
[ 14.9s] step 7      explainer                        ok
[ 14.9s] step 8      grounding_validator              ok
[ 14.9s] run         answered, 5 tool calls
```

The shape of that timeline decided the layout. Understanding is one local model
call and the tool calls are milliseconds, so the panel goes from empty to six
rows in a single instant, then waits for the sentence. While it waits the
answer card says what is happening — *"Running the plan, then writing the answer
from the figures it returns"* — because on CPU the explanation alone is 5–25 s,
and a blank card for that long reads as a hang rather than as work.

> **On showing the plan before it runs.** The panel renders the plan as pending
> rows the moment `understanding` arrives, and replaces each as its result
> comes back. In practice that pending state is over in milliseconds, because
> the MES calls are fast. It is still the right construction — it is what makes
> the refusal path legible, where the remaining steps stay on screen marked
> *skipped* so it is obvious that nothing was computed — but the demo should
> not claim a visible "watch it plan" moment that the data does not produce.

## 5. Four endings, four cards

A refusal and a rejection are answers. Rendering them as errors would
misrepresent a system working exactly as specified.

| Status | Card | What it shows |
|---|---|---|
| `answered` | Answer | headline · sentence · bottleneck · validation · working |
| `clarify` | One thing first | the question, the concrete options as buttons, *"no tool was called"* |
| `refused_missing_data` | Cannot calculate this | the named field (`parts.cycle_time_min`) and the skipped steps |
| `rejected_out_of_domain` | Outside this assistant's domain | the fixed message and an empty steps panel that says why it is empty |

Clicking a clarification option re-asks with that reading appended, and the
run comes back `answered` — the R2 loop closed on screen. Verified in a
browser, not assumed.

For a rejection the steps panel is the evidence, so it says so rather than
looking broken:

> No step ran. The request was settled before the agent reached the factory,
> so no tool was called and no row was read.

That is acceptance criterion 7, rendered.

## 6. What building the interface found in the backend

Looking at the system through a screen is a different test from looking at it
through `curl`, and it found five defects. Four were in the backend.

**A stream field that lied.** `tool_result` carried `"of": 2` while emitting
five steps — the plan length, labelled as a total. Any consumer rendering
"step 3 of 2" would have been right to. Renamed `planned_steps`, with the
distinction written down: the engine, explainer and validator steps are
appended after the plan and are legitimately not in it.

**`tool_call_count` was computed but never serialised.** The UI would have had
to recount the steps itself — and a screen that disagrees with the audit trail
about how many times the factory was read is worse than no number. It is now a
`computed_field`, so both read the same value.

**An answer that named a bottleneck when the engine found none.** With one
shift left in the week the three eligible lathes were exactly level and the
engine reported *"No single bottleneck"*. The model answered *"CNC-01 has the
available hours and the reason is material"* — grounded, incoherent, and wrong.
A tie is a finding; the validator now requires an answer not to contradict it.

**An answer that blamed the wrong kind of constraint.** The first screenshot of
the finished hero scenario read: *"This limit is set by the material
availability of 9600 units of STEEL-4140"* — while the engine had recorded 411
against a material ceiling of 9600, machine-constrained by a wide margin. Every
figure real; the sentence false. The validator now reads the clause after each
limit phrase and rejects an answer that names the constraint the engine did not
choose. Both live runs were corrected on the retry.

Both of those last two are the [§4 of `10-reliability.md`](10-reliability.md)
failure again — **grounded but wrong** — in two new disguises. The pattern is
now familiar enough to state plainly: *whenever the engine reaches a
conclusion, that conclusion needs a check, because the model will otherwise
reach for a nearby true-sounding sentence.*

The fifth was mine: the answer card's titles were keyed by run status while the
lookup used the card's tone, so the rejection card rendered with **no heading
at all**. It had been that way in every `curl` test, invisible.

## 7. Running it

```bash
make up            # postgres + model server + API + web  → http://localhost:3000
make web-dev       # the interface alone, with reload, against a local API
make web-test      # 32 unit tests
make web-lint      # eslint + tsc --noEmit
```

Next.js 16 (App Router) · React 19 · Tailwind 4 · TypeScript, strict. The
container is a standalone build: the runtime stage carries the traced server
and no `node_modules`, which is the shape an air-gapped install will want.

The page is server-rendered — the factory strip arrives with real machine state
rather than five grey placeholders — and it renders usefully with the backend
down, saying so instead of offering a question box that cannot work.

## 8. Verified in a real browser

Driven through headless Chrome against the composed stack, not asserted from
the API:

| Case | Result |
|---|---|
| S1 capacity | headline, sentence, per-machine table, formula, 5 tool calls, 8 steps |
| S4 analysis | 250 / 215 / 8 / 2.1 h, factors ranked −36 / −8 / +4, per-machine table |
| S5 maintenance | CNC-04 first, every check citing its limit, CNC-02 *not fully assessable* |
| R2 clarify | options shown, clicking one returns an `answered` run |
| R3 refusal | `parts.cycle_time_min` named, later steps shown *skipped*, 1 tool call |
| R4 rejection | fixed message, "no factory data was read", empty panel explained |
| Layout | no horizontal overflow at 1440 / 1280 / 900 px |
| Console | no errors, no failed requests |

## 9. Known limitation: the dataset on a weekend

Day 8 was built and verified on a **Saturday**, which surfaced the limitation
[`05-seed-data.md` §5](05-seed-data.md) documents — and showed it is wider than
recorded there.

The seed places CNC-03's overhaul on the working days *after* the seeding date.
On the last working day of the week none remain: the three lathes are exactly
level, capacity is 411, and there is **no bottleneck to name**. S1 and S3 lose
their story. Seeding a day earlier restores it but moves the S4 incident out of
"yesterday", so that scenario empties instead.

This is correct behaviour under the Day-1 "remaining week" rule, and a poor
demo. Six backend tests assert the seeded weekday story; they now **skip with
an explicit reason** naming this limitation rather than failing, so the suite
stays a usable gate and the cause stays visible:

```
SKIPPED tests/test_engine_oracle.py:179: no CNC-03 maintenance remains in this
        week's window, so the lathes are level and there is no bottleneck
        (docs/05-seed-data.md §5)
```

`db/verify.sql` reports the same condition as **17/20**, failing exactly the
three assertions that depend on it: the S3 bottleneck machine, "the bottleneck
has strictly fewest effective hours", and C15's material branch. Worth noting
for Day 9: on a tie the SQL oracle picks the first of the level machines while
the Python engine correctly reports *no single bottleneck* — assertion 3 is
what catches the disagreement, and the two implementations should be brought
into line.

Everything that tests *behaviour* still runs: 310 pass. Rehearse the real demo
date before the meeting (`make db-rehearse DATE=…`), and see §10.

## 10. What Day 9 picks up

1. **Make the dataset tell the story on any day** — the highest-value fix.
   Giving CNC-03 a shorter shift on the week's last working day would make it
   the bottleneck by *planned hours* rather than by maintenance, which is the
   one variant that leaves S2's "CNC-03 can continue today" true at the same
   time. It changes the cause S3 reports, so it is a documented decision, not a
   silent tweak.
2. Run the full matrix in `04-demo-scenarios.md`, including the fifteen
   phrasing variants, through the interface rather than the API.
3. Frontend end-to-end tests. The browser checks in §8 were run as a
   verification script; Day 9 should make them a suite that runs in CI.
4. Align the SQL oracle with the engine's tie rule (§9).
