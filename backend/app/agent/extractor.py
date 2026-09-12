"""Request rewriting and structured intent extraction (FR-2, FR-3).

One model call produces the rewrite and the intent together. Splitting them —
as the original component sketch did — allows the two to disagree, and a rewrite
that contradicts the intent derived from it is worse than no rewrite at all.
The call returns an `ExtractedIntent`, so a malformed reading is a validation
error, never a plausible-looking guess.

A deterministic path implements the same contract without a model. It is used
when no provider is configured and as the fallback when a configured provider
fails mid-request. That is not a shortcut: an assistant on a factory floor that
goes silent when a model endpoint blinks is worse than one that keeps answering
the five questions it was built for and says plainly that it is degraded. Every
response records which path produced it.
"""

from __future__ import annotations

import logging
import re

from app.agent.schemas import ExtractedIntent, Intent, Metric
from app.agent.vocabulary import (
    CAPABILITY_OPTIONS,
    DEFAULT_WINDOW_BY_INTENT,
    INTENT_PATTERNS,
    MACHINE_ID_PATTERN,
    MATERIAL_ID_PATTERN,
    METRIC_PATTERNS,
    PART_CONTEXT_TERMS,
    PART_ID_PATTERN,
    TIME_PATTERNS,
)
from app.llm.base import LLMClient, LLMError, LLMUsage
from app.tools.registry import registry

log = logging.getLogger(__name__)

# What each intent means, and the distinctions models actually get wrong.
# The JSON schema carries only the enum's names, so without this the model has
# to guess what "machine_health" covers as opposed to "machine_status".
INTENT_GUIDE: tuple[tuple[str, str, str], ...] = (
    (
        "production_capacity",
        "The maximum number of units of a part that could be produced in a period. "
        "Covers wording like maximum quantity, output potential, capacity, or what "
        "we are able to make.",
        "How many A12 can we produce this week?",
    ),
    (
        "bottleneck",
        "Which machine most limits production of a part, and why. Asks WHICH MACHINE, "
        "not how many units.",
        "What's slowing A12 down?",
    ),
    (
        "machine_health",
        "Whether one specifically named machine can safely keep producing. Requires "
        "a machine to be named; if the question asks which machine across the factory, "
        "it is maintenance_attention instead.",
        "Is CNC-03 safe to run?",
    ),
    (
        "machine_status",
        "What one machine is currently doing — state, job, readings. A report, not a judgement.",
        "What is the status of CNC-03?",
    ),
    (
        "production_analysis",
        "Why past output differed from plan. Always about a period that has already happened.",
        "Why was A12 production lower yesterday?",
    ),
    (
        "maintenance_attention",
        "Which machine or machines across the factory need attention, service, "
        "inspection, or look unhealthy — a ranking, with no specific machine named "
        "in the question.",
        "Any machine needing service?",
    ),
    (
        "production_orders",
        "What is planned or ordered — planned versus completed quantity, due dates.",
        "What is the planned A12 quantity?",
    ),
    (
        "material_inventory",
        "Raw material stock on hand.",
        "How much STEEL-4140 do we have?",
    ),
    ("unknown", "The request matches none of the above.", ""),
)


def _intent_guide() -> str:
    lines = []
    for name, meaning, example in INTENT_GUIDE:
        example_text = f'  e.g. "{example}"' if example else ""
        lines.append(f"- {name}: {meaning}{example_text}")
    return "\n".join(lines)


_EXTRACT_SYSTEM = """You read questions from a CNC factory manager and turn them into a \
structured request for a MES (Manufacturing Execution System) assistant.

The factory runs CNC lathes and mills that machine parts from raw material stock, on a \
shift calendar, with scheduled maintenance.

Your job is to understand the question. You must not answer it, and you must never state \
or estimate a factory value — quantities, hours, temperatures and capacities all come from \
the MES tools and a deterministic calculation engine, never from you.

Rules:
- Rewrite the question as a complete factory request. Keep the manager's meaning and add \
only what was implied. Never introduce a part, machine or number that was not there.
- Choose the single intent that matches what is actually being asked, from this list:

{intent_guide}

  Watch the near neighbours: asking WHICH MACHINE limits a part is bottleneck, not \
production_capacity. Asking whether one machine can keep running is machine_health; asking \
what it is doing is machine_status. Asking which machines across the factory need service is \
maintenance_attention. Anything about a period that has already happened, asking why, is \
production_analysis.
- "How many can we produce" means maximum feasible capacity. "How many are planned" means \
the production order quantity. "How many did we make" means recorded output. If the \
question does not settle which, mark it ambiguous rather than choosing.
- Pick the time window from the words used. "This week" means the part of the current ISO \
week that is still ahead. If no period is named, leave the default.
- List the MES tools needed, using only names from the catalogue below.
- Mark the request ambiguous only when readings differ materially. Give two to four \
concrete options when you do.

Tool catalogue:
{tool_catalogue}"""


def _tool_catalogue() -> str:
    return "\n".join(
        f"- {schema['name']}: {schema['description']}" for schema in registry.schemas()
    )


class IntentExtractor:
    """LLM extraction with a deterministic fallback behind the same contract."""

    def __init__(self, llm: LLMClient | None = None) -> None:
        self._llm = llm

    async def extract(
        self, question: str
    ) -> tuple[ExtractedIntent, str, LLMUsage | None, list[str]]:
        """Return (intent, path, usage, notes) where path is 'llm' or 'rules'."""
        notes: list[str] = []
        if self._llm is not None:
            try:
                extracted, usage = await self._llm.structured(
                    system=_EXTRACT_SYSTEM.format(
                        intent_guide=_intent_guide(), tool_catalogue=_tool_catalogue()
                    ),
                    user=question,
                    output_model=ExtractedIntent,
                    max_tokens=1024,
                )
                return self._sanitise(extracted, question, notes), "llm", usage, notes
            except LLMError as exc:
                log.warning("Intent extraction fell back to rules: %s", exc)
                notes.append(
                    f"The language model was unavailable ({exc}); rule-based reading used instead."
                )

        return self._sanitise(extract_with_rules(question), question, notes), "rules", None, notes

    @staticmethod
    def _sanitise(extracted: ExtractedIntent, question: str, notes: list[str]) -> ExtractedIntent:
        """Repair what a model gets wrong that code can get right.

        Three corrections, each guarding a failure seen with a real local model:

        **Unknown tool names are dropped.** The registry is the only source of
        callable names, so a hallucinated tool is removed and logged rather than
        attempted.

        **Entity ids are unioned with a pattern match.** Machine and part ids
        have a strict shape, so a regex finds them *more* reliably than a small
        model does — a 3B model will return the right intent for "How many A12
        can we produce this week?" and still leave `part_ids` empty, which sends
        an answerable question to a needless clarification. The model's findings
        are kept and added to, never replaced.

        **A degenerate rewrite is replaced.** Small models sometimes echo the
        intent name or truncate the question. The rewrite is shown to the user,
        so a bad one is worse than none; the deterministic rewrite is used
        instead.
        """
        known = set(registry.names())
        unknown = [name for name in extracted.required_tools if name not in known]
        if unknown:
            notes.append(f"Ignored tool name(s) the MES does not provide: {', '.join(unknown)}.")
            extracted.required_tools = [n for n in extracted.required_tools if n in known]

        lowered = question.lower()

        # A stated time expression is a literal token, so the pattern table reads
        # it more reliably than a small model infers it — and a wrong window
        # silently changes every number downstream. "Why was A12 production lower
        # yesterday?" must not be answered for this week. The model still chooses
        # the window when the question names none.
        stated_window = _match_window(lowered)
        if stated_window and stated_window != extracted.time_window:
            notes.append(
                f"Time window corrected to '{stated_window}': the question states it explicitly."
            )
            extracted.time_window = stated_window

        # Ambiguity floor. A quantity question with neither a period nor a metric
        # has three different right answers, and a model that quietly picks one is
        # the exact failure this prototype exists to prevent (FR-8). The rule is
        # narrow and only ever adds caution.
        if not extracted.ambiguous:
            rule_ambiguous, reason, options = _check_ambiguity(
                extracted.intent, extracted.metric, stated_window, lowered
            )
            if rule_ambiguous and extracted.intent is not Intent.UNKNOWN:
                extracted.ambiguous = True
                extracted.ambiguity_reason = reason
                extracted.clarification_options = options
                notes.append("Marked ambiguous: the question names neither a period nor a metric.")

        extracted.part_ids = _union(extracted.part_ids, _find_parts(question, lowered))
        extracted.machine_ids = _union(
            extracted.machine_ids, [m.group(0) for m in MACHINE_ID_PATTERN.finditer(question)]
        )
        extracted.material_ids = _union(
            extracted.material_ids, MATERIAL_ID_PATTERN.findall(question.upper())
        )

        if not _rewrite_is_usable(extracted.rewritten_question, extracted.intent, question):
            extracted.rewritten_question = _rewrite(
                extracted.intent,
                extracted.metric,
                extracted.part_ids,
                extracted.machine_ids,
                extracted.time_window,
                question.strip(),
            )
        return extracted


def _union(from_model: list[str], from_pattern: list[str]) -> list[str]:
    """Everything either source found, in order, without duplicates."""
    seen: set[str] = set()
    out: list[str] = []
    for value in [*from_model, *from_pattern]:
        key = value.strip().upper().replace(" ", "-")
        if key and key not in seen:
            seen.add(key)
            out.append(value.strip())
    return out


def _rewrite_is_usable(rewrite: str, intent: Intent, question: str) -> bool:
    """Is this rewrite worth showing the factory manager?"""
    text = (rewrite or "").strip()
    if not text:
        return False
    if intent.value in text.lower():
        return False  # the model echoed the label instead of rewriting
    if len(text) < len(question.strip()) * 0.6:
        return False  # truncated rather than expanded
    return True


async def warm_up(llm: LLMClient) -> None:
    """Run one real structured extraction so the first user question is fast.

    A local model loads into memory on its first call, and the server compiles a
    grammar for the JSON schema the first time it sees it. Both costs land inside
    whichever request comes first — which, in a demo, is the factory manager's.
    A plain completion is not enough: it warms the model but not the schema.
    """
    await llm.structured(
        system=_EXTRACT_SYSTEM.format(
            intent_guide=_intent_guide(), tool_catalogue=_tool_catalogue()
        ),
        user="How many A12 parts can we produce this week?",
        output_model=ExtractedIntent,
        max_tokens=1024,
    )


# --------------------------------------------------------------------------- rules


def extract_with_rules(question: str) -> ExtractedIntent:
    """Deterministic reading of a factory question.

    Pattern tables in `vocabulary.py` do the work, in a fixed order so that the
    more specific question shapes are tested before the general ones.
    """
    text = question.strip()
    lowered = text.lower()

    intent = _match_intent(lowered)
    part_ids = _find_parts(text, lowered)
    machine_ids = [m.group(0) for m in MACHINE_ID_PATTERN.finditer(text)]
    material_ids = [m.group(0) for m in MATERIAL_ID_PATTERN.finditer(text.upper())]

    explicit_window = _match_window(lowered)
    window = explicit_window or DEFAULT_WINDOW_BY_INTENT.get(intent.value, "this_week")
    metric = _match_metric(lowered, intent)

    ambiguous, reason, options = _check_ambiguity(intent, metric, explicit_window, lowered)

    return ExtractedIntent(
        rewritten_question=_rewrite(intent, metric, part_ids, machine_ids, window, text),
        intent=intent,
        metric=metric,
        part_ids=part_ids,
        machine_ids=machine_ids,
        material_ids=material_ids,
        time_window=window,
        required_tools=[],  # the plan template supplies these; see selector.py
        ambiguous=ambiguous,
        ambiguity_reason=reason,
        clarification_options=options,
        confidence=0.55 if intent is not Intent.UNKNOWN else 0.2,
        reasoning="Matched the factory vocabulary patterns; no language model was used.",
    )


def _match_intent(lowered: str) -> Intent:
    for intent_value, patterns in INTENT_PATTERNS:
        if any(re.search(p, lowered) for p in patterns):
            return Intent(intent_value)
    return Intent.UNKNOWN


def _match_window(lowered: str) -> str | None:
    for pattern, label in TIME_PATTERNS:
        if re.search(pattern, lowered):
            return label
    iso = re.search(r"\b(\d{4}-\d{2}-\d{2})(?:\s*\.\.\s*(\d{4}-\d{2}-\d{2}))?\b", lowered)
    if iso:
        return f"{iso.group(1)}..{iso.group(2)}" if iso.group(2) else iso.group(1)
    return None


def _match_metric(lowered: str, intent: Intent) -> Metric:
    if intent in (Intent.MACHINE_STATUS, Intent.MACHINE_HEALTH, Intent.MAINTENANCE_ATTENTION):
        return Metric.STATUS
    if intent is Intent.PRODUCTION_ANALYSIS:
        return Metric.ACTUAL_PRODUCTION
    for pattern, metric in METRIC_PATTERNS:
        if re.search(pattern, lowered):
            return Metric(metric)
    if intent is Intent.PRODUCTION_CAPACITY:
        return Metric.MAX_CAPACITY
    return Metric.NONE


def _find_parts(text: str, lowered: str) -> list[str]:
    """Part codes, but only where the sentence is about parts.

    Without the context check, 'CNC-03' would surrender '03' shaped matches and
    ordinary words could be read as part codes.
    """
    if not any(term in lowered for term in PART_CONTEXT_TERMS):
        return []
    candidates = PART_ID_PATTERN.findall(text.upper())
    machines = set(MACHINE_ID_PATTERN.findall(text.upper()))
    return [c for c in candidates if not any(c in m for m in machines)]


def _check_ambiguity(
    intent: Intent, metric: Metric, explicit_window: str | None, lowered: str
) -> tuple[bool, str | None, list[str]]:
    """Scenario R2: a quantity question with neither a period nor a metric.

    "How many A12 this week?" is answerable — the period settles it. "How many
    A12?" is not: capacity, plan and actual are three different numbers, and
    picking one silently would be the exact failure this prototype exists to
    avoid.
    """
    if intent is Intent.UNKNOWN:
        return (
            True,
            "The request does not match any factory question this assistant handles.",
            list(CAPABILITY_OPTIONS),
        )

    metric_stated = any(re.search(p, lowered) for p, _ in METRIC_PATTERNS)
    if intent is Intent.PRODUCTION_CAPACITY and explicit_window is None and not metric_stated:
        return (
            True,
            "The question asks for a quantity without saying which quantity or over what period.",
            [
                "Maximum production capacity",
                "Planned production quantity",
                "Actual production quantity",
            ],
        )
    return False, None, []


def _rewrite(
    intent: Intent,
    metric: Metric,
    part_ids: list[str],
    machine_ids: list[str],
    window: str,
    original: str,
) -> str:
    """Canonical restatement, so an elliptical question shows its full meaning."""
    part = part_ids[0] if part_ids else "the requested part"
    machine = machine_ids[0].upper().replace(" ", "-") if machine_ids else "the requested machine"
    period = window.replace("_", " ")

    match intent:
        case Intent.PRODUCTION_CAPACITY:
            return (
                f"Calculate the maximum feasible {part} production quantity for {period} "
                "using available CNC resources, scheduled maintenance and material stock."
            )
        case Intent.BOTTLENECK:
            return (
                f"Identify which CNC machine most limits {part} production for {period}, and why."
            )
        case Intent.MACHINE_HEALTH:
            return (
                f"Determine whether {machine} can continue production for {period}, "
                "based on its status, sensor readings and active maintenance."
            )
        case Intent.MACHINE_STATUS:
            return f"Report the current operating status and sensor readings for {machine}."
        case Intent.PRODUCTION_ANALYSIS:
            return (
                f"Explain why {part} production differed from plan for {period}, "
                "using recorded output, downtime and rejects."
            )
        case Intent.MAINTENANCE_ATTENTION:
            return (
                "Rank the CNC machines needing maintenance attention against the factory's "
                "condition thresholds."
            )
        case Intent.PRODUCTION_ORDERS:
            return f"List the production orders for {part} covering {period}."
        case Intent.MATERIAL_INVENTORY:
            return "Report on-hand material stock and reorder levels."
        case _:
            return original
