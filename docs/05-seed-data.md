# 05 — Virtual Factory Dataset (Day 2)

Files: [`db/seed.sql`](../db/seed.sql) (the factory) · [`db/verify.sql`](../db/verify.sql) (20 assertions).
Every value exists to make a case in [`04-demo-scenarios.md`](04-demo-scenarios.md) land.

## 1. Four rules the dataset obeys

1. **Deterministic.** No `random()`. Every value is a literal or a pure function of the date, so the
   dataset regenerates identically and Day-6 unit tests can assert exact integers.
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
| CNC-03 | LATHE | running | 52.0 | 1.8 | 46.3 | Healthy today (S2 "can continue"); low utilisation from its maintenance blocks |
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
| ALU-6061 | 180 pcs | 200 | Short, below reorder and below the 220 pcs still open on PO-3001 → C15 is **material**-constrained |
| BRZ-C932 | 1,500 pcs | 300 | Unused by any part; realistic stock noise |
| STEEL-1045 | **NULL** | 500 | Stock count in progress → "unknown", never "zero" |

Two parts with two different binding constraints means the `min(machine, material)` branch is
demonstrated, not just described.

### Shift calendar, maintenance, orders, history

- **Shifts** — 2 × 8 h Mon–Fri, 1 × 8 h Sat, none Sun, for all 5 machines, three weeks back and two
  forward (175 rows). This, not `machines.available_hours`, is the source of availability (ADR-7).
- **CNC-03 maintenance** — a 5.5 h spindle-overhaul block on every **remaining** working day of the
  current week, starting tomorrow. See §4 for why it is generated this way.
- **CNC-02 corrective maintenance** — 2.10 h on the last production day, matching
  `production_history.downtime_hours` exactly, so the S4 cause is corroborated by a second table
  rather than asserted by the LLM.
- **Other maintenance** — CNC-01, CNC-04, CNC-05 next week only; it must not touch this week's capacity.
- **Orders** — 10 rows across all five statuses, including a cancelled one.
- **History** — 90 rows, three weeks of working days. Daily variance is
  `((doy × 13 + machine_no × 7) mod 11) − 5` — reproducible, not random.

### The S4 incident (last production day, A12)

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

## 3. Verified numbers (seeded Tuesday 2026-09-08, window Tue → Sun)

| Machine | Planned h | Maintenance h | Effective h | A12 parts possible |
|---------|-----------|---------------|-------------|--------------------|
| CNC-01 | 72.0 | 0 | 72.0 | 1,234 |
| CNC-02 | 72.0 | 0 | 72.0 | 1,234 |
| CNC-03 | 72.0 | 22.0 | **50.0** | 857 |

**A12:** machine capacity 3,325 · material capacity 9,600 · **final 3,325 units**, machine-constrained,
bottleneck **CNC-03**. **C15:** machine capacity 720 · material capacity 180 · **final 180 units**,
material-constrained. These are the values the Day-6 engine must reproduce.

Capacity falls through the week because the window is the *remaining* part of it (a Day-1 decision):
4,053 Mon · 3,325 Tue · 2,597 Wed · 1,867 Thu · 1,139 Fri. CNC-03 is the bottleneck on every one.

## 4. Three deviations from the Day-1 seed plan

**CNC-03 is `running`, not `maintenance`.** The Day-1 plan copied the brief's UI mock, but the brief
also expects S2 to answer *"CNC-03 can continue production"* with healthy sensors, and S1/S3 need
CNC-03 **eligible but constrained** to be nameable as the bottleneck — a machine in `maintenance`
status is excluded from capacity entirely and cannot be a bottleneck. The mock's status strip is
cosmetic; the two scenarios are acceptance criteria, so they win. The strip shows four running
machines and one idle.

**Maintenance is 5.5 h per remaining working day, not a fixed 22 h block.** A fixed block dated
early in the week stops affecting capacity as soon as that day passes, and the bottleneck story
would quietly evaporate mid-week. Generating a block on each working day *after today* keeps two
things simultaneously true on any weekday: nothing is active on CNC-03 **today** (so S2 answers
"can continue"), and CNC-03 always has the fewest effective hours in the remaining window (so S1/S3
name it). Total is 22 h when seeded on a Tuesday.

**ALU-6061 is 180 pcs, not 420.** At 420 the material constraint stopped binding from Thursday
onwards, as the remaining machine hours shrank below it, and C15 silently became machine-bound.
180 keeps C15 material-constrained on every weekday.

## 5. Known limitation: seed for a weekday demo

`db/verify.sql` passes 20/20 on **Monday through Friday**. On Saturday the remaining window holds
only that day, no CNC-03 maintenance remains in it, and the three lathes tie — so there is no
bottleneck to name. On Sunday the window has no production hours at all and capacity is correctly 0.

Both are *correct* behaviour under the Day-1 "remaining week" rule, but they make a poor demo. On
the last working day, "CNC-03 is healthy today" (S2) and "CNC-03 is this week's constraint" (S1/S3)
genuinely cannot both hold. Rehearse the actual demo date before the meeting:

```bash
make db-rehearse DATE=2026-09-11     # seed and verify as if today were that date
make db-seed                         # afterwards, rebase back onto today
```

## 6. Timezone

"This week" is the current ISO week in **factory-local** time (Day-1 decision), not the database
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
[`02-architecture.md §5`](02-architecture.md). On Day 6 the Python engine must agree with it; if
they ever disagree, one of them is wrong, and that is exactly the check that keeps a hallucinated
number out of the demo.
