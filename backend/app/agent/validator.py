"""Answer validation: grounded in the data, and faithful to the finding (FR-7).

Two checks, because grounding alone is not correctness.

This is what makes acceptance criterion 4 enforceable rather than merely
claimed. The engine produces the numbers; the model writes the sentence; and
this module refuses to let the sentence contain a figure the engine and the
tools never produced.

It is not a hypothetical safeguard. When first measured, both local models did
exactly the thing it catches: asked to explain a capacity result, each repeated
`3,325` and `CNC-03` correctly and then added *"there are 28 hours remaining"* —
a plausible, well-formed, entirely invented number.

How the allowed set is built
----------------------------
Every numeric leaf in every tool envelope and every engine result, plus:

* **list lengths**, because "3 eligible machines" is grounded in the data even
  though no field holds the digit 3;
* **fractions as percentages**, because the engine stores a relative breach as
  `0.24` and the answer says "24 %";
* **rounded forms**, because "14 %" is a faithful rendering of `14.0`.

Identifiers are masked before numbers are extracted, so `CNC-03` is checked as a
machine that must exist rather than as the number 3. Dates are checked against
the strings the tools actually returned.

Faithful to the finding
-----------------------
A number can be genuinely present in the data and still make the answer wrong.
Asked for this week's A12 capacity, the local model once replied `317` — one
machine's contribution — instead of the `1,139` the engine calculated. Every
digit was grounded; the answer was false. So the engine's principal finding is
also checked *positively*: the headline figure and the named machine must
actually appear in the text.

What happens on failure
-----------------------
The answer is regenerated once with the offending tokens named, and if it fails
again the run falls back to the deterministic answer assembled from tool output.
A wrong number never reaches the user; the worst case is a plainer answer.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, Field

from .schemas import Intent

# Identifiers must be recognised before numbers are, or "CNC-03" donates a 3
# and "A12" donates a 12 to the numeric check.
MACHINE_ID = re.compile(r"\bCNC-\d{1,3}\b", re.IGNORECASE)
PART_ID = re.compile(r"\b[A-Z]\d{2}\b")
MATERIAL_ID = re.compile(r"\b[A-Z]{2,6}-[A-Z0-9]{3,8}\b")
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

# A number, optionally with thousands separators and decimals, not glued to a
# word character (so "8000rpm" and "step5" are not read as bare figures).
NUMBER = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?![\w])")

# Ordinals and counts a sentence needs to be readable. Allowing them avoids
# rejecting "the first factor" or "two machines" written as digits; none of them
# can carry a misleading factory quantity.
STRUCTURAL_NUMBERS: frozenset[Decimal] = frozenset(Decimal(str(n)) for n in range(0, 11))

TOLERANCE = Decimal("0.051")

# A headline whose text is an entity must be named exactly; one that is a
# verdict must not be contradicted. Demanding the literal phrase "Can continue
# production" rejected the perfectly good sentence "CNC-03 is running normally
# and is safe to keep in production" twice, and the run fell back to the
# data-only answer.
IDENTIFIER = re.compile(f"(?:{MACHINE_ID.pattern}|{PART_ID.pattern}|{MATERIAL_ID.pattern})$")
# When the engine finds no single bottleneck, an answer that names one is
# wrong however grounded its figures are. The machines are all in the data, so
# grounding has nothing to object to — this is the same substitution failure as
# "317 A12 parts", wearing a different hat.
LIMIT_CLAIM = re.compile(
    r"\b(?:bottleneck|limiting|limited by|limits it|constraint|constrains|constrained by|"
    r"slowest|fewest hours)\b",
    re.IGNORECASE,
)
# ...unless the sentence is saying the opposite: that nothing stands out.
LEVEL_CLAIM = re.compile(
    r"\b(?:no single|not a single|no one machine|none of|no bottleneck|tied|a tie|level|"
    r"equal|equally|the same|all three|all of them)\b",
    re.IGNORECASE,
)

# A figure stated with a unit. Grounding checks that 32 is somewhere in the
# data; this checks that 32 is the kind of thing the sentence says it is. The
# live scenario matrix produced "the 32 available units of A12 production" (32 was
# hours) and "56 planned shifts against 112" (hours again).
UNIT_CLAIM = re.compile(
    r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*-?\s*"
    r"(?:(?:available|planned|possible|production|processed|effective|scheduled|remaining|"
    r"rejected|total)\s+){0,2}"
    r"(units?|parts?|pcs|pieces|hours?|hrs?|h|shifts?)\b",
    re.IGNORECASE,
)
PARTS_UNITS = {"unit", "units", "part", "parts", "pcs", "piece", "pieces"}
HOURS_UNITS = {"hour", "hours", "hr", "hrs", "h"}

# A figure presented as *the* amount that can be produced. It must be a total
# the engine computed, not a component of one: "production is limited to 548
# units" (548 was CNC-03's share of 4,388) is the "317 A12 parts" failure
# again, found in a bottleneck answer.
TOTAL_CLAIM = re.compile(
    r"\b(?:up to|capped at|capacity (?:is|of)|maximum (?:is|of)|a total of|in total|"
    r"able to produce|"
    # "limiting" was the only verb this knew. A bottleneck answer then wrote
    # "constraining A12 production to 480 units" — 480 is CNC-03's own share of
    # a 3,770 total, the same substitution under a different verb.
    r"(?:limit|constrain|restrict|cap|hold|reduc)(?:s|es|ed|ing)?"
    r"\s+(?:\w+\s+){0,3}?(?:to|at))"
    r"\s+(?:about |around |approximately |only )?"
    r"(\d{1,3}(?:,\d{3})+|\d+)(?![\w.])"
    # "limits the output at 32 available hours" states hours, not a total.
    r"(?!\s*(?:(?:available|planned|effective)\s+)?(?:hours?|hrs?|h)\b)",
    re.IGNORECASE,
)

# Output stated as a quantity of hours. Seen live, asked what is slowing A12
# down: "CNC-03 limits A12 production to 28 hours this week." 28 is CNC-03's own
# availability; A12 production is limited to 3,770 parts. TOTAL_CLAIM lets an
# hours figure through on purpose — "limited to 28 available hours" is a true
# sentence about a machine — so what is wrong here is the object of the limit,
# and that is what this reads: production, output or the part itself, sitting
# between the limit and the hours.
HOURS_AS_OUTPUT = re.compile(
    r"\blimit(?:s|ed|ing)?|\bcap(?:s|ped)?|\brestrict(?:s|ed|ing)?", re.IGNORECASE
)
OUTPUT_WORD = re.compile(r"\b(?:production|output|throughput|parts)\b", re.IGNORECASE)
TO_HOURS = re.compile(
    r"\bto\s+(?:about |around |approximately |only |just )?"
    r"(\d+(?:[.,]\d+)?)\s*(?:available\s+|planned\s+|effective\s+)?"
    r"(?:h|hr|hrs|hour|hours)\b",
    re.IGNORECASE,
)

# Which of a bottleneck's two reasons a sentence blames.
# A figure presented as the factory's limit for a reading. Found while measuring
# sampling temperatures: at 0.9 the model wrote "a utilisation of 46.3%, which is
# above the 52.0% threshold" — 52 is CNC-03's temperature in °C, and the
# utilisation limit is 90%. Every digit was grounded; the limit was invented.
THRESHOLD_CLAIM = re.compile(
    r"(?<![\w.])(\d{1,3}(?:\.\d+)?)\s*(%|°\s?C|mm/s)\s*"
    r"(?:\w+\s+){0,2}?(?:limit|threshold|maximum|max|ceiling)\b",
    re.IGNORECASE,
)
# Which reading each unit belongs to, for reading the limits off the run.
THRESHOLD_UNITS = {"%": "%", "°c": "°C", "° c": "°C", "mm/s": "mm/s"}

# Read from the clause that states the reason, not from the whole answer:
# "CNC-03 is limited to 28 available hours, 48 h fewer planned than the other
# machines plus 20 h of maintenance" names both without attributing anything to
# either, and reading the whole sentence rejected it.
REASON_CLAUSE = re.compile(
    r"\b(?:because(?:\s+of)?|due to|owing to|as a result of|driven by|mainly|"
    r"the (?:main|larger|primary) reason(?:\s+is)?)\b(.*)",
    re.IGNORECASE | re.DOTALL,
)
SHIFT_WORDS = re.compile(
    r"\b(?:shift|shifts|staffing|fewer\s+(?:\w+\s+){0,2}?planned|planned\s+hours|"
    r"hours\s+planned)\b",
    re.IGNORECASE,
)
MAINTENANCE_WORDS = re.compile(r"\b(?:maintenance|overhaul|servicing|service)\b", re.IGNORECASE)

# "Maintenance is active" about a machine the engine cleared to run. Seen live:
# "CNC-03 can continue production. Maintenance is active for 24 hours." — the 24
# was the overhaul booked for later in the week.
MAINTENANCE_ACTIVE = re.compile(
    r"\b(?:maintenance\s+(?:is\s+)?(?:currently\s+)?(?:active|in progress|underway|ongoing)|"
    r"under maintenance|being (?:serviced|maintained))\b",
    re.IGNORECASE,
)
NEGATION_BEFORE = re.compile(r"(?:\bno\b|\bnot\b|n't)\W*(?:\w+\W+){0,2}$", re.IGNORECASE)

# Rejects add to a shortfall; they never reduce it. Seen live: "the 8 parts
# rejected, though this reduced the overall shortfall" — the reduction was
# CNC-03's over-production, a different factor.
REDUCES = re.compile(r"\b(?:reduc\w*|offset\w*|compensat\w*|made up for|lessen\w*)\b", re.I)
CLAUSE_BREAK = re.compile(
    r",|;|\bwhile\b|\bwhereas\b|\bthough\b|\balthough\b|\bbut\b|\bwhich\b", re.I
)
PRIMARY = re.compile(r"\b(?:main|primary|biggest|largest|leading|principal)\b", re.I)
DOWNTIME_WORDS = re.compile(r"\bdowntime\b|\bstop(?:page)?\b|\bfault\b|\bbreakdown\b")
OVER_PRODUCTION = re.compile(r"over-?produc\w*|more than planned|above plan|ahead of plan", re.I)

# A verdict that the machine may not run. The negation has to attach to running:
# the live scenario matrix rejected a correct "CNC-03 can continue production …
# readings do not exceed the limits" twice, because "do not" anywhere in the
# answer counted as "cannot continue", and the run fell back to the data-only text.
NEGATIVE_VERDICT = re.compile(
    r"\b(?:cannot|can't|can not|could not|must not|should not|unable to|not able to|"
    r"do(?:es)? not|is not|isn't|not safe to|unsafe to)\s+(?:\w+\s+){0,2}?"
    r"(?:continue|run|operate|produce|production|be run|keep running)\b"
    r"|\b(?:stop|halt|pause)\s+(?:\w+\s+){0,2}?(?:production|running|operation|the machine)\b"
    r"|\btake (?:it |CNC-\d+ )?out of service\b",
    re.IGNORECASE,
)


class GroundingReport(BaseModel):
    grounded: bool
    numbers_checked: int = 0
    entities_checked: int = 0
    unsupported_numbers: list[str] = Field(default_factory=list)
    unsupported_entities: list[str] = Field(default_factory=list)
    unsupported_dates: list[str] = Field(default_factory=list)
    missing_claims: list[str] = Field(
        default_factory=list,
        description="Findings the engine produced that the answer failed to state",
    )
    wrong_claims: list[str] = Field(
        default_factory=list,
        description="Statements built from real figures that the data contradicts",
    )
    leaked_labels: list[str] = Field(
        default_factory=list,
        description="Fact-sheet scaffolding the draft repeated back to the reader",
    )
    note: str = ""

    def feedback(self) -> str:
        """What to tell the model so a second attempt can succeed."""
        parts: list[str] = []
        if self.unsupported_numbers:
            parts.append(
                "these numbers do not appear in the factory data: "
                + ", ".join(self.unsupported_numbers)
            )
        if self.unsupported_entities:
            parts.append(
                "these machines or parts were not in the data: "
                + ", ".join(self.unsupported_entities)
            )
        if self.unsupported_dates:
            parts.append("these dates were not in the data: " + ", ".join(self.unsupported_dates))
        if self.missing_claims:
            parts.append("the answer must state " + "; and ".join(self.missing_claims))
        if self.wrong_claims:
            parts.append("these statements contradict the data: " + "; ".join(self.wrong_claims))
        if self.leaked_labels:
            parts.append(
                "it opened with a label copied from the facts ("
                + ", ".join(self.leaked_labels)
                + ") instead of a sentence — say the same thing as ordinary English, "
                "beginning with the machine or the figure itself"
            )
        return "; ".join(parts)


def _walk(node: Any, numbers: set[Decimal], strings: set[str]) -> None:
    """Collect every numeric leaf, string leaf and list length in a payload."""
    if isinstance(node, dict):
        for value in node.values():
            _walk(value, numbers, strings)
    elif isinstance(node, list):
        # "3 eligible machines" is grounded even though no field holds a 3.
        numbers.add(Decimal(len(node)))
        for item in node:
            _walk(item, numbers, strings)
    elif isinstance(node, bool):
        return
    elif isinstance(node, (int, float)):
        numbers.add(Decimal(str(node)))
    elif isinstance(node, str):
        strings.add(node)


def _expand(numbers: set[Decimal]) -> set[Decimal]:
    """Add the forms an answer may legitimately use for the same value."""
    expanded: set[Decimal] = set(STRUCTURAL_NUMBERS)
    for value in numbers:
        expanded.add(value)
        expanded.add(abs(value))
        # A relative breach of 0.24 is written as "24 %".
        if abs(value) <= 1:
            expanded.add((abs(value) * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
            expanded.add((abs(value) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        # 14.0 may be written "14"; 18.5 may be rounded to "19".
        expanded.add(abs(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
        expanded.add(abs(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return expanded


def allowed_values(run) -> tuple[set[Decimal], set[str]]:
    """Everything the tools returned and the engine computed, for this run."""
    numbers: set[Decimal] = set()
    strings: set[str] = set()

    for step in run.steps:
        if step.detail:
            _walk(step.detail, numbers, strings)
    for payload in (run.capacity, run.constraint, run.analysis, run.headline, run.bottleneck):
        if payload is not None:
            _walk(payload.model_dump(mode="json"), numbers, strings)
    for health in run.health:
        _walk(health.model_dump(mode="json"), numbers, strings)
    if run.window is not None:
        _walk(run.window.model_dump(mode="json"), numbers, strings)

    return _expand(numbers), strings


def _extract(text: str) -> tuple[list[str], list[str], list[str]]:
    """Pull identifiers, dates and bare numbers out of a draft answer."""
    entities = [m.group(0).upper() for m in MACHINE_ID.finditer(text)]
    entities += MATERIAL_ID.findall(text)
    entities += PART_ID.findall(text)
    dates = ISO_DATE.findall(text)

    # Mask what has already been accounted for, so its digits are not re-read.
    masked = ISO_DATE.sub(" ", text)
    masked = MACHINE_ID.sub(" ", masked)
    masked = MATERIAL_ID.sub(" ", masked)
    masked = PART_ID.sub(" ", masked)

    numbers = [m.group(0) for m in NUMBER.finditer(masked)]
    return numbers, sorted(set(entities)), dates


def _as_decimal(token: str) -> Decimal | None:
    try:
        return Decimal(token.replace(",", ""))
    except InvalidOperation:
        return None


def _contains_number(text: str, value: float | int) -> bool:
    """Is this figure actually stated, in any reasonable rendering?"""
    target = Decimal(str(value))
    for token in NUMBER.finditer(text):
        candidate = _as_decimal(token.group(0))
        if candidate is not None and abs(candidate - target) <= TOLERANCE:
            return True
    return False


# For these intents the answer is a machine, not a quantity, and the headline
# says so: a bottleneck run headlines the machine it found, not the capacity it
# ranked the machines by. The set stays because a figure may still ride along
# in a headline — demanding it in the prose turns a correct bottleneck answer
# into a rejected one. The machine is required instead, below.
_NAMES_A_MACHINE = {Intent.BOTTLENECK, Intent.MACHINE_HEALTH, Intent.MACHINE_STATUS}


# Which kind of thing a sentence says is doing the limiting. The engine already
# decided — `min(machine_capacity, material_capacity)` has exactly one winner —
# so an answer that names the other one contradicts the calculation it is
# describing, however real its figures are.
LIMIT_PHRASE = re.compile(
    r"\b(?:limit(?:ed|s|ing)?|constrain(?:ed|t|ts|s)?|bottleneck(?:ed)?|capped|restricted)\b",
    re.IGNORECASE,
)
MATERIAL_WORD = re.compile(
    r"\b(?:material|materials|stock|inventory|steel|alu|brz)\b", re.IGNORECASE
)
MACHINE_WORD = re.compile(
    r"\b(?:machine|machines|lathe|lathes|mill|mills|cnc|hours?|capacity|shift|shifts)\b",
    re.IGNORECASE,
)


def _blamed_constraints(text: str) -> set[str]:
    """What the sentence says is limiting production, if anything.

    Each limit phrase is read with the clause that follows it, and whichever of
    the two kinds is named first is taken as what that phrase blames. Reading
    the whole sentence instead would find "material" in "…limited by machine
    hours; material stock is ample" and call a correct answer wrong.
    """
    blamed: set[str] = set()
    for phrase in LIMIT_PHRASE.finditer(text):
        clause = re.split(r"[.;]", text[phrase.end() : phrase.end() + 60])[0]
        material = MATERIAL_WORD.search(clause)
        machine = MACHINE_WORD.search(clause)
        if material and (not machine or material.start() < machine.start()):
            blamed.add("material")
        elif machine:
            blamed.add("machine")
    return blamed


def _headline_text_claim(text: str, headline_text: str, label: str) -> str | None:
    """What a non-numeric headline obliges the answer to say.

    An identifier is a fact with one spelling: S5's `CNC-04` must appear, or
    the answer is about a different machine. A verdict is a yes/no, and English
    has many ways to write each — so the polarity is checked instead of the
    wording.
    """
    if IDENTIFIER.match(headline_text):
        if headline_text.upper() not in text.upper():
            return f"'{headline_text}' ({label})"
        return None

    lowered = headline_text.lower()
    said_no = bool(NEGATIVE_VERDICT.search(text))
    if lowered.startswith("cannot") and not said_no:
        return f"that {label} cannot continue production"
    if lowered.startswith("can ") and said_no:
        return f"that {label} can continue production"
    return None


def check_key_claims(text: str, run) -> list[str]:
    """The answer must state what the engine concluded.

    Grounding alone is not correctness. A model can pick a number that is
    genuinely in the data and still be wrong: asked for this week's A12
    capacity it once answered with `317`, one machine's contribution, instead of
    the `1,139` the engine calculated. Every digit was grounded; the answer was
    not true.

    So the principal finding is checked positively — the headline figure and the
    named machine must appear. These are the claims the demo turns on, and an
    answer that omits or replaces them is rejected and rewritten.
    """
    missing: list[str] = []

    headline = run.headline
    if headline is not None:
        wants_number = headline.value is not None and run.intent not in _NAMES_A_MACHINE
        if wants_number and not _contains_number(text, headline.value):
            unit = f" {headline.unit}" if headline.unit else ""
            missing.append(f"the calculated figure {headline.value:g}{unit} ({headline.label})")
        if headline.text:
            claim = _headline_text_claim(text, headline.text, headline.label)
            if claim is not None:
                missing.append(claim)

    if run.bottleneck is not None and run.bottleneck.machine_id.upper() not in text.upper():
        missing.append(f"{run.bottleneck.machine_id} as the limiting machine")

    # The binding constraint is a conclusion, not a flavour of words. Asked for
    # this week's A12 capacity the model wrote "this limit is set by the
    # material availability of 9600 units" — while the engine had recorded
    # machine-constrained, 411 against a material ceiling of 9600.
    if run.capacity is not None:
        binding = run.capacity.binding_constraint
        blamed = _blamed_constraints(text)
        if blamed and binding not in blamed:
            other = "material availability" if binding == "machine" else "machine hours"
            correct = "machine hours" if binding == "machine" else "material availability"
            missing.append(
                f"that {correct} is what limits production here, not {other} — "
                f"the engine calculated this as {binding}-constrained"
            )

    # A tie is a finding, not the absence of one. On the last working day of the
    # week the eligible machines can be exactly level, and the honest answer
    # says so — the local model instead answered "CNC-01 has the available
    # hours and the reason is material", every token of it grounded.
    if (
        run.constraint is not None
        and run.constraint.bottleneck is None
        and MACHINE_ID.search(text)
        and LIMIT_CLAIM.search(text)
        and not LEVEL_CLAIM.search(text)
    ):
        missing.append(
            "that no single machine is the constraint — the engine found none: "
            f"{run.constraint.explanation}"
        )

    return missing


def _typed_values(node: Any, path: tuple[str, ...], hours: set[Decimal], parts: set[Decimal]):
    """Split numeric leaves by what they measure, read from the field that holds them."""
    if isinstance(node, dict):
        for key, value in node.items():
            _typed_values(value, (*path, str(key)), hours, parts)
    elif isinstance(node, list):
        for item in node:
            _typed_values(item, path, hours, parts)
    elif isinstance(node, bool):
        return
    elif isinstance(node, (int, float)):
        key = path[-1].lower() if path else ""
        joined = "/".join(path).lower()
        value = Decimal(str(node))
        if "hour" in key or key.endswith("_h") or "duration" in key or "hours_by" in joined:
            hours.add(value)
        elif any(
            w in key
            for w in (
                "capacity",
                "parts",
                "quantity",
                "shortfall",
                "impact",
                "lost",
                "reorder",
                "delta",
            )
        ):
            parts.add(value)


def _rounded(values: set[Decimal]) -> set[Decimal]:
    out: set[Decimal] = set()
    for value in values:
        out |= {
            abs(value),
            abs(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP),
            abs(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP),
        }
    return out


def _mask_identifiers(text: str) -> str:
    masked = ISO_DATE.sub(" ", text)
    masked = MACHINE_ID.sub(" ", masked)
    masked = MATERIAL_ID.sub(" ", masked)
    return PART_ID.sub(" ", masked)


def check_contradictions(text: str, run) -> list[str]:
    """Statements made of real figures and real names that the data says are false.

    Grounding asks whether each figure exists. These ask whether the sentence
    around it is true — the class of failure the live scenario matrix found in the
    local model's prose after every figure had passed: a figure with the wrong
    unit, a component presented as the total, maintenance "active" on a machine
    cleared to run, and rejects attributed to one machine or said to reduce the
    shortfall.
    """
    wrong: list[str] = []
    masked = _mask_identifiers(text)

    hours: set[Decimal] = set()
    parts: set[Decimal] = set()
    for step in run.steps:
        if step.detail:
            _typed_values(step.detail, (), hours, parts)
    for payload in (run.capacity, run.constraint, run.analysis):
        if payload is not None:
            _typed_values(payload.model_dump(mode="json"), (), hours, parts)
    hours, parts = _rounded(hours), _rounded(parts)

    def near(value: Decimal, pool: set[Decimal]) -> bool:
        return any(abs(value - candidate) <= TOLERANCE for candidate in pool)

    for match in UNIT_CLAIM.finditer(masked):
        value = _as_decimal(match.group(1))
        unit = match.group(2).lower()
        if value is None:
            continue
        if unit in PARTS_UNITS and not near(value, parts) and near(value, hours):
            wrong.append(f"{match.group(1)} is a figure in hours, not {unit}")
        elif unit in HOURS_UNITS and not near(value, hours) and near(value, parts):
            wrong.append(f"{match.group(1)} is a count of parts, not {unit}")
        elif unit.startswith("shift") and value > 10 and near(value, hours):
            wrong.append(f"{match.group(1)} is a figure in hours, not a number of shifts")

    capacity = run.capacity
    if capacity is not None:
        totals = {
            Decimal(v)
            for v in (
                capacity.final_capacity,
                capacity.machine_capacity,
                capacity.material_capacity,
            )
            if v is not None
        }
        for match in TOTAL_CLAIM.finditer(masked):
            value = _as_decimal(match.group(1))
            if value is not None and value not in totals:
                wrong.append(
                    f"{match.group(1)} is not the total that can be produced — the engine "
                    f"calculated {capacity.final_capacity}"
                )

    bottleneck = run.constraint.bottleneck if run.constraint is not None else None
    if bottleneck is not None and capacity is not None:
        for limit in HOURS_AS_OUTPUT.finditer(masked):
            tail = masked[limit.end() : limit.end() + 80]
            hours_match = TO_HOURS.search(tail)
            if hours_match is None:
                continue
            # Only when what is being limited is the output itself. "CNC-03 is
            # limited to 28 hours" says nothing false about production.
            between = tail[: hours_match.start()]
            if not OUTPUT_WORD.search(between):
                continue
            wrong.append(
                f"production is counted in parts, not hours — the engine calculated "
                f"{capacity.final_capacity} {capacity.part_id} units; say instead that "
                f"{bottleneck.machine_id} has {hours_match.group(1)} available production "
                f"hours, which is what makes it the constraint"
            )
            break

    # Blaming the smaller half of the problem. Seen live: "CNC-03 limits A12
    # production because of scheduled maintenance" — the shift pattern takes 48
    # hours off it, the maintenance 20.
    ranked_reasons = (
        bottleneck is not None
        and bottleneck.main_cause is not None
        and bottleneck.shift_shortfall_hours > 0
        and bottleneck.maintenance_hours > 0
    )
    if ranked_reasons:
        reason = REASON_CLAUSE.search(text)
        if reason is not None:
            blamed = reason.group(1)
            blames_shift = bool(SHIFT_WORDS.search(blamed))
            blames_maintenance = bool(MAINTENANCE_WORDS.search(blamed))
            if bottleneck.main_cause == "shift pattern" and blames_maintenance and not blames_shift:
                wrong.append(
                    f"the larger reason is {bottleneck.machine_id}'s shorter shift pattern "
                    f"({bottleneck.shift_shortfall_hours:g} h fewer planned than the other "
                    f"machines), not the {bottleneck.maintenance_hours:g} h of maintenance"
                )
            elif bottleneck.main_cause == "maintenance" and blames_shift and not blames_maintenance:
                wrong.append(
                    f"the larger reason is the {bottleneck.maintenance_hours:g} h of scheduled "
                    f"maintenance, not {bottleneck.machine_id}'s shift pattern"
                )

    # Limits are the factory's, from `rule_thresholds`. A sentence that states a
    # different one for a reading is wrong however real its digits are.
    limits: dict[str, set[Decimal]] = {}
    names: dict[str, str] = {}

    def remember(unit: str | None, display: str, bounds) -> None:
        key = THRESHOLD_UNITS.get((unit or "").strip().lower())
        if key is None:
            return
        for bound in bounds:
            if bound is not None:
                limits.setdefault(key, set()).add(Decimal(str(bound)))
        names.setdefault(key, display)

    # Every limit the MES supplied, not only the two the health rules apply.
    # Utilisation is deliberately not a condition rule (`engine/rules.py`), but
    # it has a threshold row — and it was a utilisation sentence that invented
    # one.
    for step in run.steps:
        rows = ((step.detail or {}).get("data") or {}).get("thresholds") or []
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict):
                remember(
                    row.get("unit"),
                    str(row.get("display_name") or row.get("rule_key") or "reading"),
                    (row.get("warning_threshold"), row.get("critical_threshold")),
                )
    for health in run.health:
        for check in health.checks:
            remember(
                check.unit,
                check.display_name,
                (check.warning_threshold, check.critical_threshold),
            )
    for match in THRESHOLD_CLAIM.finditer(text):
        unit = THRESHOLD_UNITS.get(match.group(2).strip().lower())
        value = _as_decimal(match.group(1))
        if unit is None or value is None or unit not in limits:
            continue
        if not any(abs(value - bound) <= TOLERANCE for bound in limits[unit]):
            stated = ", ".join(f"{bound:g}" for bound in sorted(limits[unit]))
            wrong.append(
                f"the factory's {names[unit].lower()} limit is {stated} {unit}, "
                f"not {match.group(1)} {unit}"
            )

    for health in run.health:
        if not health.can_produce or health.machine_id.upper() not in text.upper():
            continue
        for match in MAINTENANCE_ACTIVE.finditer(text):
            if NEGATION_BEFORE.search(text[: match.start()]):
                continue
            wrong.append(f"no maintenance is active on {health.machine_id} today")
            break

    analysis = run.analysis
    if analysis is not None and analysis.rejected_quantity:
        with_rejects = [m for m in analysis.by_machine if m.rejected_quantity]
        breakdown = ", ".join(f"{m.machine_id} ({m.rejected_quantity})" for m in with_rejects)
        for sentence in re.split(r"(?<=[.;!?])\s+", text):
            if "reject" not in sentence.lower():
                continue
            # Attribution is read per clause: "8 parts were rejected, while CNC-03
            # produced 4 more than planned" names CNC-03 without blaming it.
            for clause in CLAUSE_BREAK.split(sentence):
                if "reject" not in clause.lower():
                    continue
                named = {m.group(0).upper() for m in MACHINE_ID.finditer(clause)}
                total = analysis.rejected_quantity
                if not (
                    len(named) == 1
                    and len(with_rejects) > 1
                    and _contains_number(_mask_identifiers(clause), total)
                ):
                    continue
                machine = next(iter(named))
                own = next(
                    (m.rejected_quantity for m in with_rejects if m.machine_id == machine), 0
                )
                if own != total:
                    wrong.append(
                        f"the {total} rejects were across {breakdown}, not {machine} alone"
                    )
            if REDUCES.search(sentence) and not OVER_PRODUCTION.search(sentence):
                wrong.append("rejects add to the shortfall; they do not reduce it")

    # The ranking is the engine's. Seen live: "The main reason was the 8 parts
    # rejected … The secondary factor was CNC-02's 2.1 hours of downtime" — the
    # engine had ranked downtime first, 36 parts against 8.
    if analysis is not None:
        ranked = [f for f in analysis.factors if f.impact_parts > 0]
        if len(ranked) >= 2:
            top = ranked[0]
            for sentence in re.split(r"(?<=[.;!?])\s+", text):
                if not PRIMARY.search(sentence):
                    continue
                kind = _factor_kind(sentence)
                if kind is not None and kind != top.kind:
                    wrong.append(
                        f"the main factor was {top.label.lower()} ({top.impact_parts} parts), "
                        f"not {'rejects' if kind == 'rejects' else 'downtime'}"
                    )

    return list(dict.fromkeys(wrong))


def _factor_kind(sentence: str) -> str | None:
    """Which kind of factor a sentence names as its subject, if only one."""
    lowered = sentence.lower()
    rejects = "reject" in lowered
    downtime = bool(DOWNTIME_WORDS.search(lowered))
    if rejects and not downtime:
        return "rejects"
    if downtime and not rejects:
        return "downtime"
    return None


# The fact sheet's own scaffolding. An answer that repeats it is reading the
# worksheet aloud: asked for A12 capacity, the model opened with
# "RESULT — Estimated A12 capacity: 3770 units." Every figure was right and the
# sentence was unreadable. The system prompt forbids it; this makes it checkable,
# so a leak is rewritten rather than shown.
SCAFFOLDING = re.compile(
    r"(?:^|\n)\s*(?:RESULT\b|FACTS\b|-{3,}\s*$|Question:|Interpreted as:|Period:)"
    r"|RESULT\s*[—:-]",
    re.IGNORECASE | re.MULTILINE,
)


def check_scaffolding(text: str) -> list[str]:
    """Labels from the fact sheet that must not reach the reader."""
    found = set()
    for match in SCAFFOLDING.finditer(text):
        label = match.group(0).strip().strip("—:-").strip()
        found.add(label or "a fact-sheet label")
    return sorted(found)


def validate_answer(text: str, run) -> GroundingReport:
    """Check a draft answer against what this run actually retrieved."""
    if not text.strip():
        return GroundingReport(grounded=False, note="The answer was empty.")

    numbers, entities, dates = _extract(text)
    allowed_numbers, allowed_strings = allowed_values(run)

    known_entities = {e.upper() for e in allowed_strings if isinstance(e, str)}
    resolved = run.understanding.entities if run.understanding is not None else None
    if resolved is not None:
        known_entities |= {e.id.upper() for e in resolved.parts + resolved.machines}
        known_entities |= {m.upper() for m in resolved.known_machine_ids}
        known_entities |= {p.upper() for p in resolved.known_part_ids}

    unsupported_numbers: list[str] = []
    for token in numbers:
        value = _as_decimal(token)
        if value is None:
            continue
        if not any(abs(value - candidate) <= TOLERANCE for candidate in allowed_numbers):
            unsupported_numbers.append(token)

    unsupported_entities = [e for e in entities if e not in known_entities]
    unsupported_dates = [d for d in dates if d not in allowed_strings]

    missing_claims = check_key_claims(text, run)
    wrong_claims = check_contradictions(text, run)
    leaked_labels = check_scaffolding(text)
    grounded = not (
        unsupported_numbers
        or unsupported_entities
        or unsupported_dates
        or missing_claims
        or wrong_claims
        or leaked_labels
    )
    report = GroundingReport(
        grounded=grounded,
        numbers_checked=len(numbers),
        entities_checked=len(entities),
        unsupported_numbers=sorted(set(unsupported_numbers)),
        unsupported_entities=unsupported_entities,
        unsupported_dates=sorted(set(unsupported_dates)),
        missing_claims=missing_claims,
        wrong_claims=wrong_claims,
        leaked_labels=leaked_labels,
    )
    report.note = (
        f"{len(numbers)} number(s) and {len(entities)} entity reference(s) checked against "
        f"the retrieved data."
        if grounded
        else "Ungrounded: " + report.feedback()
    )
    return report
