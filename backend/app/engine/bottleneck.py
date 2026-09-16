"""Which machine limits a part, and why (S3).

Pure ranking over the per-machine lines the capacity engine already produced.
Two judgements matter more than the sort.

**A tie is not a bottleneck.** If two eligible machines share the lowest
effective hours, nothing distinguishes them and naming one would be arbitrary.
The engine returns `None` and says so. This is the honest answer on the last
working day of the week, when no maintenance remains in the window and the
lathes are level — the case `docs/05-seed-data.md` §5 documents.

**Material outranks machines.** If stock is the binding constraint, the limiting
factor is not a machine at all, and saying "CNC-03" would point the manager at
the wrong problem.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.engine.capacity import CapacityResult, MachineCapacityLine


class BottleneckFinding(BaseModel):
    machine_id: str
    effective_hours: float
    planned_hours: float
    maintenance_hours: float
    parts_possible: int
    cause: str = Field(description="Why this machine has the fewest hours, largest reason first")
    margin_hours: float = Field(
        default=0.0, description="How far below the next machine it sits, in hours"
    )
    shift_shortfall_hours: float = Field(
        default=0.0,
        description="Hours this machine is short of the best-staffed peer, before maintenance",
    )
    main_cause: str | None = Field(
        default=None,
        description=(
            "Which reason takes the most hours away: 'shift pattern' or 'maintenance'. "
            "The answer must not blame the smaller one."
        ),
    )


class ConstraintFinding(BaseModel):
    """What limits this part, whichever kind of thing it turns out to be."""

    kind: str = Field(description="'machine' | 'material' | 'none'")
    bottleneck: BottleneckFinding | None = None
    material_id: str | None = None
    material_capacity: int | None = None
    explanation: str
    ranking: list[BottleneckFinding] = Field(default_factory=list)


def _cause(
    line: MachineCapacityLine, peers: list[MachineCapacityLine]
) -> tuple[str, str | None, float]:
    """What takes hours away from this machine: the phrase, the main reason, its size.

    It is read after "because of", so it must be a noun phrase — the live scenario
    run printed "because of only 56 h of shifts are planned for it", which is
    not English. And it names every reason that applies: a machine can be short
    of hours because fewer shifts are planned for it *and* because maintenance
    takes some of those, and naming only the maintenance would send the manager
    to reschedule an overhaul that is not the larger problem.

    **The reasons are ordered by size, largest first, and the largest is named.**
    CNC-03 is short 48 hours of shifts and 20 hours of maintenance, so
    "because of scheduled maintenance" — which the live model wrote — points at
    the smaller half of the problem. Ordering it here is what lets the validator
    require it (`10-reliability.md` §4).

    A machine with nothing taking hours away says so, rather than borrowing the
    bottleneck's explanation — the ranking once described every machine as
    having "the fewest planned production hours".
    """
    if line.planned_hours == 0:
        return "no shifts planned in this period", None, 0.0

    others = [peer.planned_hours for peer in peers if peer.machine_id != line.machine_id]
    best_staffed = max(others) if others else line.planned_hours
    shortfall = round(max(0.0, best_staffed - line.planned_hours), 2)

    reasons: list[tuple[float, str, str]] = []
    if shortfall > 0:
        reasons.append(
            (
                shortfall,
                "shift pattern",
                f"a shorter shift pattern ({line.planned_hours:g} planned hours, "
                f"against {best_staffed:g} planned hours on other machines)",
            )
        )
    if line.maintenance_hours > 0:
        reasons.append(
            (
                line.maintenance_hours,
                "maintenance",
                f"{line.maintenance_hours:g} h of scheduled maintenance",
            )
        )
    if not reasons:
        return "no shift or maintenance reduction in this period", None, shortfall

    reasons.sort(key=lambda reason: -reason[0])
    phrase = " and ".join(text for _, _, text in reasons) + " in this period"
    return phrase, reasons[0][1], shortfall


def _finding(
    line: MachineCapacityLine, peers: list[MachineCapacityLine], margin: float = 0.0
) -> BottleneckFinding:
    cause, main_cause, shortfall = _cause(line, peers)
    return BottleneckFinding(
        machine_id=line.machine_id,
        effective_hours=line.effective_hours,
        planned_hours=line.planned_hours,
        maintenance_hours=line.maintenance_hours,
        parts_possible=line.parts_possible,
        cause=cause,
        margin_hours=round(margin, 2),
        shift_shortfall_hours=shortfall,
        main_cause=main_cause,
    )


def identify_constraint(capacity: CapacityResult) -> ConstraintFinding:
    """What is actually limiting this part's output."""
    eligible = sorted(
        (line for line in capacity.machines if line.eligible),
        key=lambda line: (line.effective_hours, line.machine_id),
    )
    ranking = [_finding(line, eligible) for line in eligible]

    if capacity.binding_constraint == "material":
        return ConstraintFinding(
            kind="material",
            material_id=capacity.material_id,
            material_capacity=capacity.material_capacity,
            explanation=(
                f"Material is the limit, not a machine: {capacity.available_quantity:g} "
                f"of {capacity.material_id} allows {capacity.material_capacity} units, "
                f"below the {capacity.machine_capacity} the machines could run."
            ),
            ranking=ranking,
        )

    if not eligible:
        return ConstraintFinding(
            kind="none", explanation="No eligible machine is available in this period.", ranking=[]
        )

    lowest = eligible[0]
    tied = [line for line in eligible if line.effective_hours == lowest.effective_hours]
    if len(tied) > 1:
        return ConstraintFinding(
            kind="none",
            explanation=(
                f"No single bottleneck: {', '.join(t.machine_id for t in tied)} all have "
                f"{lowest.effective_hours:g} available hours in this period."
            ),
            ranking=ranking,
        )

    margin = eligible[1].effective_hours - lowest.effective_hours if len(eligible) > 1 else 0.0
    finding = _finding(lowest, eligible, margin)
    return ConstraintFinding(
        kind="machine",
        bottleneck=finding,
        explanation=(
            f"{finding.machine_id} is the primary bottleneck for {capacity.part_id}: it has "
            f"only {finding.effective_hours:g} available production hours in this period "
            f"because of {finding.cause}."
        ),
        ranking=ranking,
    )
