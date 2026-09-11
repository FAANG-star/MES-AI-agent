"""Why output differed from plan (S4).

Every percentage in the S4 answer is derived here, from recorded rows — none is
stored, and none comes from the model. `docs/04-demo-scenarios.md` fixes the
definitions:

    shortfall        = planned − produced
    pct_below_plan   = 100 × shortfall / planned
    reject_rate      = 100 × rejected / (produced + rejected)
    parts_lost       = downtime_hours × 60 / cycle_time_min

The last one is what turns a list of numbers into an explanation. Downtime in
hours means nothing to a shortfall counted in parts; converting it through the
cycle time puts both on the same scale, so the factors can be **ranked by
quantified impact** rather than asserted in a plausible order. On the seeded
incident that is 2.1 h → 36 parts against a 35-part shortfall, which is why the
answer can say the downtime accounts for the miss and mean it.

Rounding matches `db/verify.sql` to one decimal place, because the two must
agree.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, Field

from app.schemas.mes import ProductionHistoryRow


def _round1(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


class ContributingFactor(BaseModel):
    kind: str = Field(description="'downtime' | 'rejects' | 'unexplained' | 'offset'")
    label: str
    impact_parts: int = Field(description="Effect on output, in parts, so factors are comparable")
    detail: str
    machines: list[str] = Field(default_factory=list)


class MachineDelta(BaseModel):
    machine_id: str
    planned_quantity: int
    produced_quantity: int
    delta: int = Field(description="produced − planned; negative is a shortfall")
    downtime_hours: float = 0.0
    downtime_reason: str | None = None


class ProductionAnalysis(BaseModel):
    part_id: str | None = None
    planned_quantity: int
    produced_quantity: int
    rejected_quantity: int
    downtime_hours: float
    shortfall: int = Field(description="planned − produced; negative means over plan")
    pct_below_plan: float | None = None
    reject_rate_pct: float | None = None
    parts_lost_to_downtime: int | None = None
    by_machine: list[MachineDelta] = Field(default_factory=list)
    factors: list[ContributingFactor] = Field(default_factory=list)
    summary: str = ""


def analyse_production(
    rows: list[ProductionHistoryRow],
    *,
    part_id: str | None = None,
    cycle_time_min: float | None = None,
) -> ProductionAnalysis:
    """Plan versus actual, with the contributing factors ranked by impact."""
    planned = sum(r.planned_quantity for r in rows)
    produced = sum(r.produced_quantity for r in rows)
    rejected = sum(r.rejected_quantity for r in rows)
    downtime = sum(Decimal(str(r.downtime_hours)) for r in rows)
    shortfall = planned - produced

    analysis = ProductionAnalysis(
        part_id=part_id,
        planned_quantity=planned,
        produced_quantity=produced,
        rejected_quantity=rejected,
        downtime_hours=float(downtime),
        shortfall=shortfall,
    )
    if not rows:
        analysis.summary = "No production is recorded for this period."
        return analysis

    if planned > 0:
        analysis.pct_below_plan = _round1(Decimal(shortfall) * 100 / Decimal(planned))
    processed = produced + rejected
    if processed > 0:
        analysis.reject_rate_pct = _round1(Decimal(rejected) * 100 / Decimal(processed))

    by_machine: dict[str, MachineDelta] = {}
    for row in rows:
        entry = by_machine.setdefault(
            row.machine_id,
            MachineDelta(
                machine_id=row.machine_id, planned_quantity=0, produced_quantity=0, delta=0
            ),
        )
        entry.planned_quantity += row.planned_quantity
        entry.produced_quantity += row.produced_quantity
        entry.delta = entry.produced_quantity - entry.planned_quantity
        entry.downtime_hours = round(entry.downtime_hours + row.downtime_hours, 2)
        if row.downtime_reason:
            entry.downtime_reason = row.downtime_reason
    analysis.by_machine = [by_machine[m] for m in sorted(by_machine)]

    factors: list[ContributingFactor] = []

    if downtime > 0 and cycle_time_min:
        lost = int(
            (downtime * 60 / Decimal(str(cycle_time_min))).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        stopped = [m for m in analysis.by_machine if m.downtime_hours > 0]
        reasons = sorted({m.downtime_reason for m in stopped if m.downtime_reason})
        factors.append(
            ContributingFactor(
                kind="downtime",
                label=f"{float(downtime):g} hours of downtime",
                impact_parts=lost,
                detail=(
                    f"{float(downtime):g} h lost on "
                    f"{', '.join(m.machine_id for m in stopped) or 'the line'}"
                    + (f" ({'; '.join(reasons)})" if reasons else "")
                    + f" — about {lost} parts at a {cycle_time_min:g} min cycle."
                ),
                machines=[m.machine_id for m in stopped],
            )
        )
        analysis.parts_lost_to_downtime = lost
    elif downtime > 0:
        factors.append(
            ContributingFactor(
                kind="downtime",
                label=f"{float(downtime):g} hours of downtime",
                impact_parts=0,
                detail=(
                    f"{float(downtime):g} h of downtime was recorded; its effect in parts "
                    "cannot be quantified without a cycle time."
                ),
                machines=[m.machine_id for m in analysis.by_machine if m.downtime_hours > 0],
            )
        )

    if rejected > 0:
        factors.append(
            ContributingFactor(
                kind="rejects",
                label=f"{analysis.reject_rate_pct:g}% rejection rate",
                impact_parts=rejected,
                detail=(
                    f"{rejected} parts rejected of {processed} processed "
                    f"({analysis.reject_rate_pct:g}%)."
                ),
            )
        )

    over = [m for m in analysis.by_machine if m.delta > 0]
    if over and shortfall > 0:
        gained = sum(m.delta for m in over)
        factors.append(
            ContributingFactor(
                kind="offset",
                label="partly offset by over-production",
                impact_parts=-gained,
                detail=(
                    f"{', '.join(m.machine_id for m in over)} produced {gained} above plan, "
                    "reducing the net shortfall."
                ),
                machines=[m.machine_id for m in over],
            )
        )

    # Rank by magnitude of effect, so the "main reason" is the largest one and
    # not merely the first thing checked.
    factors.sort(key=lambda f: abs(f.impact_parts), reverse=True)
    analysis.factors = factors

    if shortfall > 0:
        lead = (
            f"{part_id or 'Production'} was {analysis.pct_below_plan:g}% below plan "
            f"({produced} produced against {planned} planned)."
        )
        if factors:
            lead += f" The main factor was {factors[0].label}."
    elif shortfall < 0:
        lead = (
            f"{part_id or 'Production'} was above plan: {produced} produced against "
            f"{planned} planned."
        )
    else:
        lead = f"{part_id or 'Production'} met plan exactly at {produced} units."
    analysis.summary = lead
    return analysis
