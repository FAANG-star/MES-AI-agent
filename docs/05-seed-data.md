# 05 — Virtual Factory Dataset

Files: [`db/seed.sql`](../db/seed.sql) (the factory) · [`db/verify.sql`](../db/verify.sql) (20 assertions).
Every value exists to make a case in [`04-demo-scenarios.md`](04-demo-scenarios.md) land.

## 1. Four rules the dataset obeys

1. **Deterministic.** No `random()`. Every value is a literal or a pure function of the date, so the
   dataset regenerates identically and engine unit tests can assert exact integers.
2. **Date-relative.** All dates derive from the current ISO week. Re-running the seed rebases the
   whole factory onto today, so the demo tells the same story in October as in September.
3. **Idempotent.** Truncate-then-insert. Safe to run repeatedly; also runs automatically on first
   container start via `docker-entrypoint-initdb.d` (`schema.sql` → `seed.sql` → `verify.sql`).
4. **Scenario-driven.** Nothing is decorative. Where a value looks odd, a comment in the SQL says
   which scenario requires it.

## 2. The factory

### Machines

| Machine | Type | Status | Temp °C | Vibration mm/s | Util % | Why these values |
|---------|------|--------|---------|----------------|--------|------------------|
| CNC-01 | LATHE | running | **72.5** | 1.2 | 84.2 | Breaches the 70 °C limit → a second attention candidate for S5 |
| CNC-02 | LATHE | running | 61.0 | **NULL** | 79.6 | Vibration sensor offline → must be "not assessable", never "healthy" |
| CNC-03 | LATHE | running | 52.0 | 1.8 | 46.3 | Healthy today (S2 "can continue"); low utilisation — it runs one shift a day and has its overhaul booked |
| CNC-04 | MILL | idle | 66.5 | **3.1** | 31.8 | Breaches the 2.5 mm/s limit by 24 % → the S5 answer |
| CNC-05 | MILL | running | 64.2 | 2.0 | 88.1 | Healthy; utilisation deliberately under 90 % |

S5 is not a walkover: CNC-01 and CNC-04 each breach **exactly one** threshold, so the ranking must
fall through to the tie-break on relative severity (24 % vs 3.6 %) to select CNC-04.

### Parts and materials

| Part | Cycle time | Material | Qty/part | Machine type |
|------|-----------|----------|----------|--------------|
| A12 Bearing | 3.5 min | STEEL-4140 | 1.0 | CNC_LATHE |
| B20 Shaft | **NULL** | STEEL-4140 | 1.2 | CNC_LATHE |
| C15 Housing | 12.0 min | ALU-6061 | 1.0 | CNC_MILL |

B20's missing cycle time is the point, not an omission: it is a newly introduced part whose routing
has not been time-studied. The agent must name `parts.cycle_time_min` and refuse (R3).

| Material | Stock | Reorder | Role |
|----------|-------|---------|------|
| STEEL-4140 | 9,600 pcs | 2,000 | Plentiful → A12 is **machine**-constrained (hero scenario) |
| ALU-6061 | 120 pcs | 200 | Short, below reorder and below the 220 pcs still open on PO-3001 → C15 is **material**-constrained on every day of the week |
| BRZ-C932 | 1,500 pcs | 300 | Unused by any part; realistic stock noise |
| STEEL-1045 | **NULL** | 500 | Stock count in progress → "unknown", never "zero" |

Two parts with two different binding constraints means the `min(machine, material)` branch is
demonstrated, not just described.

### Shift calendar, maintenance, orders, history

- **Shifts** — the factory runs **seven days a week**: 2 × 8 h a day on every machine except
  CNC-03, which is staffed for **one 8 h shift**. Three weeks back and two forward (175 rows). This,
  not `machines.available_hours`, is the source of availability (ADR-7).
- **CNC-03 maintenance** — a 4 h spindle-overhaul block on every **remaining** day of the current
  week, starting tomorrow. See §4 for why it is generated this way.
- **CNC-02 corrective maintenance** — 2.10 h yesterday, matching
  `production_history.downtime_hours` exactly, so the S4 cause is corroborated by a second table
  rather than asserted by the LLM.
- **Other maintenance** — CNC-01, CNC-04, CNC-05 next week only; it must not touch this week's capacity.
- **Orders** — 10 rows across all five statuses, including a cancelled one.
- **History** — daily records for three weeks, every day. Daily variance is
  `((doy × 13 + machine_no × 7) mod 11) − 5` — reproducible, not random.

### The S4 incident (yesterday, A12)

| Machine | Planned | Produced | Rejected | Downtime |
|---------|---------|----------|----------|----------|
| CNC-01 | 100 | 97 | 3 | — |
| CNC-02 | 100 | **64** | 3 | **2.1 h** — tool changer fault |
| CNC-03 | 50 | 54 | 2 | — |
| **Total** | **250** | **215** | **8** | **2.1 h** |

The numbers are internally consistent, which is what makes the agent's explanation defensible:
2.1 h at a 3.5 min cycle = **36 parts**, against a total shortfall of **35** — so the downtime alone
accounts for the miss, CNC-03's +4 overproduction offsets the rest, and the 8 rejects
(**3.6 %** of 223 processed) are a genuine secondary factor. Shortfall is exactly **14.0 %**.
No percentage is stored; the engine derives all of them.

## 3. Verified numbers (seeded Monday 2026-09-14, window Mon → Sun)

| Machine | Planned h | Maintenance h | Effective h | A12 parts possible |
|---------|-----------|---------------|-------------|--------------------|
| CNC-01 | 112.0 | 0 | 112.0 | 1,920 |
| CNC-02 | 112.0 | 0 | 112.0 | 1,920 |
| CNC-03 | 56.0 | 24.0 | **32.0** | 548 |

**A12:** machine capacity 4,388 · material capacity 9,600 · **final 4,388 units**, machine-constrained,
bottleneck **CNC-03** — *a shorter shift pattern (56 h planned, against 112 h on other machines) and
24 h of scheduled maintenance*. **C15:** machine capacity 1,120 · material capacity 120 · **final 120
units**, material-constrained.

Capacity falls through the week because the window is the *remaining* part of it (a scoping decision),
and the story now holds on **every** day, Sunday included:

| | Mon | Tue | Wed | Thu | Fri | Sat | Sun |
|---|---|---|---|---|---|---|---|
| A12 capacity | 4,388 | 3,770 | 3,153 | 2,536 | 1,918 | 1,301 | 685 |
| CNC-03 effective h | 32 | 28 | 24 | 20 | 16 | 12 | 8 |
| Bottleneck | CNC-03 | CNC-03 | CNC-03 | CNC-03 | CNC-03 | CNC-03 | CNC-03 |
| C15 | 120, material | 120, material | 120, material | 120, material | 120, material | 120, material | 120, material |

`make test-week` proves it: for each day it reseeds the factory as that day, runs `db/verify.sql`
(20/20) and runs the whole backend suite with the backend's calendar pinned to the same day.

## 4. Deviations from the initial seed plan

**CNC-03 is `running`, not `maintenance`.** The initial plan copied the brief's UI mock, but the brief
also expects S2 to answer *"CNC-03 can continue production"* with healthy sensors, and S1/S3 need
CNC-03 **eligible but constrained** to be nameable as the bottleneck — a machine in `maintenance`
status is excluded from capacity entirely and cannot be a bottleneck. The mock's status strip is
cosmetic; the two scenarios are acceptance criteria, so they win. The strip shows four running
machines and one idle.

**Maintenance is a block per remaining day, not a fixed block.** A fixed block dated early in the
week stops affecting capacity as soon as that day passes. Generating one on each day *after today*
keeps nothing active on CNC-03 **today**, so S2 answers "can continue".

**The factory runs seven days, and CNC-03 runs one shift.** The original calendar (Mon–Fri
double shift, Saturday single, Sunday off) told the story only Monday to Friday. On Saturday no
CNC-03 maintenance remained, the three lathes tied and S1/S3 had no bottleneck; on Sunday "this
week" held no hours at all; on Monday "yesterday" was a Sunday with nothing to explain. The two
constraints pull against each other on the last day of the week — being the bottleneck needs hours
taken away *in the window*, and S2 needs nothing active *today* — so maintenance alone cannot carry
the story. A **single-shift CNC-03 is a structural constraint**: it is the bottleneck whether or not
any maintenance remains, and nothing about it is "active today". Running every day makes
"yesterday" always a production day.

**ALU-6061 is 120 pcs.** The smallest window (Sunday alone) gives the two mills
2 × 16 h × 60 / 12 min = 160 parts; stock must sit below that for C15 to stay material-bound every
day. It was 420 in the initial plan and 180 in the first dataset, each time lowered for the same reason.

## 5. Every day of the week

Originally, `db/verify.sql` passed 20/20 only Monday to Friday, and the demo story broke on the
weekend and on Mondays (§4). With seven-day operation and a single-shift CNC-03 it passes on all
seven days, and so does the full backend suite:

```bash
make test-week        # seed + oracle + every test, once as each day of this week
```

To rehearse a particular day end to end — dataset **and** backend agreeing on the date:

```bash
make db-rehearse DATE=2026-09-18          # seed and verify as if today were that date
FACTORY_TODAY=2026-09-18 make up          # pin the backend's calendar to the same day
make db-seed                              # afterwards: unset FACTORY_TODAY and rebase onto today
```

While `FACTORY_TODAY` is set, `/api/health` reports `pinned: true` and the web interface shows a
**Rehearsal** badge, because a pinned calendar left on would quietly answer about the wrong day.

## 5a. The dataset is relative, so it goes out of date

Every date here is laid out around whatever "today" was when `db/seed.sql` ran.
That is what makes the demo work on any day of the week — and it means a
database seeded yesterday is a database about yesterday.

**It does not fail loudly, which is the problem.** Asked the morning after a
seed which machine limited A12, the agent answered *"CNC-03, 20 effective hours
of 40 planned"* — right against the rows, right against the SQL oracle, and a
day out of date. What breaks is the story rather than the arithmetic:

| Scenario | With a day-old seed |
|---|---|
| S2 — CNC-03 cleared to run today | The overhaul block that should start *tomorrow* is active **today**, so CNC-03 is refused |
| S4 — yesterday's shortfall | "Yesterday" holds no production at all; there is nothing to explain |
| S1/S3 — capacity and bottleneck | Still consistent, with different figures from the table above |

**So the stack now says so.** `app/dataset.py` compares the newest
`production_history` row with the factory's yesterday — the seed always writes
history up to and including yesterday, which makes it the one reliable signal.
The result is reported three ways: a warning in the backend log at startup, a
`dataset` block on `/api/health`, and an amber **Data 2 days old · run make
db-seed** badge in the top bar, beside the rehearsal badge and for the same
reason.

Nothing reseeds itself. The backend reads the factory; rewriting it on a hunch
is what a read-only tool layer exists to prevent, and an automatic reseed
mid-demo would change the numbers under the presenter. `make db-seed` is one
command, and `make db-verify` confirms 20/20 afterwards.

## 6. Timezone

"This week" is the current ISO week in **factory-local** time (a scoping decision), not the database
server's UTC. The seed sets `FACTORY_TIMEZONE` on the database itself, so every later session —
backend, psql, tools — inherits it and no query has to remember to convert.

The factory timezone is **`Asia/Tokyo`** (UTC+9), set in `.env` and used as the default in
`db/seed.sql` and the `Makefile`. Move the factory with `make factory-timezone ZONE=Asia/Shanghai`,
which validates the name, updates `.env`, reseeds and recreates the backend. Viewers in other zones
do not need this: the web interface shows times in their own zone while answers keep the factory's
days (see [`11-frontend.md`](11-frontend.md) §Time zones). Getting this wrong shifts "today" by a day for part of every
night — with the database left on UTC, the demo window would move backwards by one day from
09:00 JST onward — which silently changes every capacity number. To run the factory in another
timezone, use `make factory-timezone ZONE=…`.

## 7. Verifying

```bash
make db-up        # first start runs schema.sql, seed.sql and verify.sql automatically
make db-verify    # 20 assertions: expected vs actual vs PASS/FAIL
```

`db/verify.sql` is an **independent oracle**: it recomputes the capacity, bottleneck, health-ranking
and plan-vs-actual figures in plain SQL, straight from the formula in
[`02-architecture.md §5`](02-architecture.md). The Python calculation engine must agree with it; if
they ever disagree, one of them is wrong, and that is exactly the check that keeps a hallucinated
number out of the demo.
