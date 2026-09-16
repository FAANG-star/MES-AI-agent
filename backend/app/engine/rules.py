"""Machine-condition rules (S2, S5).

Thresholds are **not** in this file. They are read from `rule_thresholds` and
passed in (ADR-4), so a plant can retune a limit without a code change and every
verdict can cite the row it was compared against.

Three rules the demo depends on:

**A missing reading is never "healthy".** A NULL sensor is `not_assessable`, and
a machine with one cannot be declared fit — it can only be declared partly
unknown. Silence from a sensor is not a passing grade.

**Maintenance overrides sensors.** A machine in `maintenance` status, or with an
active maintenance window today, cannot produce however good its readings are.

**Attention is ranked, and ties are broken by severity.** Two machines each
breaching one threshold are not equally urgent: 3.1 mm/s against a 2.5 limit is
24 % over, while 72.5 °C against 70 is 3.6 %. Breach count first, then the worst
relative breach. Utilisation is deliberately excluded — it is bottleneck
context, not a condition fault — which is also how `db/verify.sql` ranks.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.mes import MachineStatus, RuleThreshold

# The readings that constitute a condition check, and the machine field each reads.
HEALTH_RULES: tuple[tuple[str, str], ...] = (
    ("machine.temperature_c", "temperature_c"),
    ("machine.vibration_mm_s", "vibration_mm_s"),
)

NOT_PRODUCING_STATUSES = frozenset({"maintenance", "down"})


class ThresholdCheck(BaseModel):
    rule_key: str
    display_name: str
    unit: str
    reading: float | None = None
    warning_threshold: float | None = None
    critical_threshold: float | None = None
    level: str = Field(description="'normal' | 'warning' | 'critical' | 'not_assessable'")
    relative_breach: float | None = Field(
        default=None, description="How far over the warning limit, as a fraction"
    )
    verdict: str = Field(description="One line naming the reading, the limit and the outcome")


class MachineHealth(BaseModel):
    machine_id: str
    status: str
    can_produce: bool
    reason: str
    checks: list[ThresholdCheck] = Field(default_factory=list)
    breaches: int = 0
    worst_relative_breach: float | None = Field(
        default=None,
        description=(
            "How close the worst assessable reading sits to its warning limit, as a fraction: "
            "positive is over the limit, negative is headroom. Ranks machines below the limit "
            "sensibly too — 68 °C deserves more attention than 52 °C."
        ),
    )
    fully_assessable: bool = True
    attention_note: str | None = None
    # Carried through for the answer, not used by any rule: a question about a
    # machine's *status* is answered by what it is doing, and without these the
    # only facts available were the threshold checks — so every status answer
    # read like a safety verdict.
    current_job: str | None = None
    utilization_pct: float | None = None


def _check(machine: MachineStatus, threshold: RuleThreshold, field: str) -> ThresholdCheck:
    reading = getattr(machine, field, None)
    base = ThresholdCheck(
        rule_key=threshold.rule_key,
        display_name=threshold.display_name,
        unit=threshold.unit,
        reading=reading,
        warning_threshold=threshold.warning_threshold,
        critical_threshold=threshold.critical_threshold,
        level="not_assessable",
        verdict=f"{threshold.display_name}: no reading available — not assessable.",
    )
    if reading is None or threshold.warning_threshold is None:
        return base

    warning = threshold.warning_threshold
    critical = threshold.critical_threshold
    if critical is not None and reading >= critical:
        level = "critical"
    elif reading >= warning:
        level = "warning"
    else:
        level = "normal"

    base.level = level
    base.relative_breach = round((reading - warning) / warning, 4) if warning else None
    word = {"normal": "Normal", "warning": "Warning", "critical": "Critical"}[level]
    comparison = "below" if level == "normal" else "at or above"
    base.verdict = (
        f"{threshold.display_name}: {reading:g} {threshold.unit} — {word} "
        f"({comparison} the {warning:g} {threshold.unit} limit)."
    )
    return base


def evaluate_machine(
    machine: MachineStatus,
    thresholds: list[RuleThreshold],
    *,
    under_maintenance_today: bool = False,
) -> MachineHealth:
    """Can this machine keep producing, and how much attention does it need?"""
    by_key = {t.rule_key: t for t in thresholds}
    checks = [_check(machine, by_key[key], field) for key, field in HEALTH_RULES if key in by_key]

    breaching = [c for c in checks if c.level in ("warning", "critical")]
    unassessable = [c for c in checks if c.level == "not_assessable"]
    # Over every reading that could be assessed, not only the breaching ones: a
    # machine at 68 °C is closer to trouble than one at 52 °C, and the ranking
    # should say so once the breach counts are equal. This also keeps the engine
    # in step with the SQL oracle, which ranks the same way.
    worst = max((c.relative_breach for c in checks if c.relative_breach is not None), default=None)

    if machine.status in NOT_PRODUCING_STATUSES:
        can_produce, reason = False, f"{machine.machine_id} is {machine.status}."
    elif under_maintenance_today:
        can_produce, reason = False, f"{machine.machine_id} has maintenance active today."
    elif any(c.level == "critical" for c in breaching):
        can_produce = False
        reason = f"{machine.machine_id} has a reading past its stop limit: " + "; ".join(
            c.verdict for c in breaching if c.level == "critical"
        )
    elif breaching:
        can_produce = True
        reason = f"{machine.machine_id} can continue production, but " + "; ".join(
            c.verdict for c in breaching
        )
    else:
        can_produce = True
        reason = f"{machine.machine_id} can continue production."

    if unassessable:
        reason += (
            " Note: "
            + ", ".join(c.display_name.lower() for c in unassessable)
            + " could not be assessed because no reading is available."
        )

    return MachineHealth(
        machine_id=machine.machine_id,
        status=machine.status,
        can_produce=can_produce,
        reason=reason,
        checks=checks,
        breaches=len(breaching),
        worst_relative_breach=worst,
        fully_assessable=not unassessable,
        attention_note=None,
        current_job=machine.current_job,
        utilization_pct=machine.utilization_pct,
    )


def rank_attention(healths: list[MachineHealth]) -> list[MachineHealth]:
    """Most in need of attention first: breach count, then worst relative breach.

    A machine whose sensors cannot be read is never sorted above one with a real
    breach, but it is flagged, because "we do not know" is a maintenance task of
    its own.
    """
    ranked = sorted(
        healths,
        key=lambda h: (
            h.breaches,
            # A machine whose sensors cannot be read ranks above one known to be
            # healthy with the same breach count: "unknown" warrants more
            # attention than "fine". The specification left this corner open;
            # `db/verify.sql` applies the same rule so the two agree.
            0 if h.fully_assessable else 1,
            h.worst_relative_breach if h.worst_relative_breach is not None else -1,
        ),
        reverse=True,
    )
    for health in ranked:
        if health.breaches:
            worst = max(
                (c for c in health.checks if c.level in ("warning", "critical")),
                key=lambda c: c.relative_breach if c.relative_breach is not None else -1,
            )
            over = (
                f"{worst.relative_breach * 100:.0f}%" if worst.relative_breach is not None else "?"
            )
            health.attention_note = (
                f"{worst.display_name} is {worst.reading:g} {worst.unit}, "
                f"{over} over the {worst.warning_threshold:g} {worst.unit} limit."
            )
        elif not health.fully_assessable:
            health.attention_note = "A sensor reading is unavailable, so its condition is unknown."
    return ranked
