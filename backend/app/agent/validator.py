"""Answer validation: grounded in the data, and faithful to the finding (FR-7).

Two checks, because grounding alone is not correctness.

This is what makes acceptance criterion 4 enforceable rather than merely
claimed. The engine produces the numbers; the model writes the sentence; and
this module refuses to let the sentence contain a figure the engine and the
tools never produced.

It is not a hypothetical safeguard. Measured on Day 4, both local models did
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

NEGATIVE_VERDICT = re.compile(
    r"\b(?:cannot|can't|can not|could not|must not|should not|unable to|not able to|"
    r"do(?:es)? not|is not|isn't|stop|halt|take (?:it )?out of service)\b",
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


# For these intents the answer is a machine, not a quantity. The headline still
# carries a figure — S3 reports the capacity it ranked the machines by — but
# demanding it in the prose turns a correct bottleneck answer into a rejected
# one. The machine is required instead, below.
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
    grounded = not (
        unsupported_numbers or unsupported_entities or unsupported_dates or missing_claims
    )
    report = GroundingReport(
        grounded=grounded,
        numbers_checked=len(numbers),
        entities_checked=len(entities),
        unsupported_numbers=sorted(set(unsupported_numbers)),
        unsupported_entities=unsupported_entities,
        unsupported_dates=sorted(set(unsupported_dates)),
        missing_claims=missing_claims,
    )
    report.note = (
        f"{len(numbers)} number(s) and {len(entities)} entity reference(s) checked against "
        f"the retrieved data."
        if grounded
        else "Ungrounded: " + report.feedback()
    )
    return report
