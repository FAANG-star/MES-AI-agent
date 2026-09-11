"""The Python engine against the SQL oracle.

`db/verify.sql` has computed capacity, bottleneck, health ranking and
plan-versus-actual in plain SQL since Day 2, straight from the specification in
`docs/02-architecture.md` §5. The Day-6 engine computes the same things in
Python, from data fetched through the repository.

Two implementations, two languages, one specification. These tests run both over
the live seeded factory and require them to agree **exactly** — not
approximately, and not on a fixture, but on whatever the seed produced today.

If they ever disagree, one of them is wrong, and the disagreement is the alarm.
That is what stands behind the claim that no number in this demo was invented.
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.engine import analyse_production, calculate_capacity, evaluate_machine, rank_attention
from app.engine.bottleneck import identify_constraint
from app.repositories.mes_repository import MesRepository
from app.timewindow import FactoryClock, resolve_window
from tests.conftest import requires_db

pytestmark = requires_db


CAPACITY_ORACLE = """
WITH win AS (SELECT $1::date AS d_from, $2::date AS d_to),
part AS (SELECT * FROM parts WHERE part_id = $3),
eff AS (
    SELECT m.machine_id,
           m.status::text AS st,
           COALESCE((SELECT SUM(s.planned_hours) FROM machine_shift_calendar s, win w
                      WHERE s.machine_id = m.machine_id
                        AND s.shift_date BETWEEN w.d_from AND w.d_to), 0) AS planned_h,
           COALESCE((SELECT SUM(mt.duration_hours) FROM maintenance mt, win w
                      WHERE mt.machine_id = m.machine_id
                        AND mt.maintenance_date BETWEEN w.d_from AND w.d_to
                        AND mt.maintenance_status IN ('scheduled', 'in_progress')), 0) AS maint_h
      FROM machines m, part p
     WHERE m.machine_type = p.required_machine_type
)
SELECT
  (SELECT SUM(floor(GREATEST(0, e.planned_h - e.maint_h) * 60 / p.cycle_time_min))::int
     FROM eff e, part p WHERE e.st IN ('running', 'idle'))
       AS machine_capacity,
  (SELECT floor(i.available_quantity / p.material_qty_per_unit)::int
     FROM part p JOIN inventory i ON i.material_id = p.material_id)
       AS material_capacity,
  (SELECT e.machine_id FROM eff e WHERE e.st IN ('running', 'idle')
    ORDER BY GREATEST(0, e.planned_h - e.maint_h), e.machine_id LIMIT 1)
       AS bottleneck,
  (SELECT GREATEST(0, e.planned_h - e.maint_h) FROM eff e WHERE e.st IN ('running', 'idle')
    ORDER BY GREATEST(0, e.planned_h - e.maint_h), e.machine_id LIMIT 1)
       AS bottleneck_hours,
  (SELECT count(*) FROM eff e WHERE e.st IN ('running', 'idle')
     AND GREATEST(0, e.planned_h - e.maint_h) =
         (SELECT MIN(GREATEST(0, e2.planned_h - e2.maint_h)) FROM eff e2
           WHERE e2.st IN ('running', 'idle')))
       AS tied_at_minimum
"""

HEALTH_ORACLE = """
SELECT m.machine_id,
       COALESCE((m.temperature_c  >= t.warn)::int, 0)
         + COALESCE((m.vibration_mm_s >= v.warn)::int, 0)                   AS breaches,
       GREATEST(COALESCE((m.temperature_c  - t.warn) / t.warn,  -1),
                COALESCE((m.vibration_mm_s - v.warn) / v.warn, -1))         AS worst,
       (m.temperature_c IS NULL OR m.vibration_mm_s IS NULL)                AS not_assessable
  FROM machines m,
       (SELECT warning_threshold AS warn FROM rule_thresholds
         WHERE rule_key = 'machine.temperature_c')  t,
       (SELECT warning_threshold AS warn FROM rule_thresholds
         WHERE rule_key = 'machine.vibration_mm_s') v
 ORDER BY breaches DESC, not_assessable DESC, worst DESC
"""

ANALYSIS_ORACLE = """
SELECT SUM(planned_quantity)                                                   AS planned,
       SUM(produced_quantity)                                                  AS produced,
       SUM(rejected_quantity)                                                  AS rejected,
       SUM(downtime_hours)                                                     AS downtime_h,
       round(100.0 * (SUM(planned_quantity) - SUM(produced_quantity))
                   / NULLIF(SUM(planned_quantity), 0), 1)                      AS pct_below_plan,
       round(100.0 * SUM(rejected_quantity)
                   / NULLIF(SUM(produced_quantity) + SUM(rejected_quantity), 0), 1)
                                                                               AS reject_rate_pct,
       round(SUM(downtime_hours) * 60
             / (SELECT cycle_time_min FROM parts WHERE part_id = $2))          AS parts_lost
  FROM production_history
 WHERE part_id = $2 AND production_date = $1::date
"""


async def _capacity_from_engine(repo: MesRepository, part_id: str, window):
    part = await repo.part(part_id)
    availability = await repo.availability(window.start, window.end, part.required_machine_type)
    inventory = (await repo.inventory(part.material_id))[0]
    return calculate_capacity(
        part=part, availability=availability, inventory=inventory, window=window
    )


@pytest.mark.parametrize("part_id", ["A12", "C15"])
async def test_capacity_matches_the_sql_oracle(pool, repo, part_id):
    """The whole calculation, in two languages, over today's live data."""
    clock = FactoryClock(get_settings().factory_timezone)
    window = resolve_window("this_week", clock)

    engine = await _capacity_from_engine(repo, part_id, window)
    async with pool.acquire() as conn:
        sql = await conn.fetchrow(CAPACITY_ORACLE, window.start, window.end, part_id)

    assert engine.machine_capacity == sql["machine_capacity"], "machine capacity disagrees"
    assert engine.material_capacity == sql["material_capacity"], "material capacity disagrees"
    assert engine.final_capacity == min(sql["machine_capacity"], sql["material_capacity"])


@pytest.mark.parametrize("part_id", ["A12", "C15"])
async def test_the_bottleneck_matches_the_sql_oracle(pool, repo, part_id):
    clock = FactoryClock(get_settings().factory_timezone)
    window = resolve_window("this_week", clock)

    engine = await _capacity_from_engine(repo, part_id, window)
    finding = identify_constraint(engine)
    async with pool.acquire() as conn:
        sql = await conn.fetchrow(CAPACITY_ORACLE, window.start, window.end, part_id)

    if engine.binding_constraint == "material":
        assert finding.kind == "material"
        return
    if sql["tied_at_minimum"] > 1:
        assert finding.kind == "none", "a tie must not be reported as a bottleneck"
        return

    assert finding.bottleneck is not None
    assert finding.bottleneck.machine_id == sql["bottleneck"]
    assert finding.bottleneck.effective_hours == pytest.approx(float(sql["bottleneck_hours"]))


async def test_the_attention_ranking_matches_the_sql_oracle(pool, repo):
    machines = await repo.machines()
    thresholds = await repo.thresholds()
    ranked = rank_attention([evaluate_machine(m, thresholds) for m in machines])

    async with pool.acquire() as conn:
        rows = await conn.fetch(HEALTH_ORACLE)

    assert [h.machine_id for h in ranked] == [r["machine_id"] for r in rows]
    by_id = {h.machine_id: h for h in ranked}
    for row in rows:
        health = by_id[row["machine_id"]]
        # SQL yields NULL breaches where a reading is NULL; Python counts the
        # readings it could assess. Both must agree on what is assessable.
        assert health.fully_assessable == (not row["not_assessable"])
        assert health.breaches == row["breaches"]


async def test_the_production_analysis_matches_the_sql_oracle(pool, repo):
    last_day = await repo.last_production_day()
    rows = await repo.history(last_day, last_day, part_id="A12")
    part = await repo.part("A12")
    engine = analyse_production(rows, part_id="A12", cycle_time_min=part.cycle_time_min)

    async with pool.acquire() as conn:
        sql = await conn.fetchrow(ANALYSIS_ORACLE, last_day, "A12")

    assert engine.planned_quantity == sql["planned"]
    assert engine.produced_quantity == sql["produced"]
    assert engine.rejected_quantity == sql["rejected"]
    assert engine.pct_below_plan == pytest.approx(float(sql["pct_below_plan"]))
    assert engine.reject_rate_pct == pytest.approx(float(sql["reject_rate_pct"]))
    assert engine.parts_lost_to_downtime == int(sql["parts_lost"])


async def test_the_seeded_story_still_holds(pool, repo):
    """The demo depends on these being true, not just on the two paths agreeing."""
    clock = FactoryClock(get_settings().factory_timezone)
    window = resolve_window("this_week", clock)

    a12 = await _capacity_from_engine(repo, "A12", window)
    assert a12.binding_constraint == "machine", "A12 is the machine-constrained hero scenario"
    assert a12.final_capacity > 0

    c15 = await _capacity_from_engine(repo, "C15", window)
    assert c15.binding_constraint == "material", "C15 demonstrates the other branch"
