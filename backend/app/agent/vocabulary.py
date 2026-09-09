"""The factory's language, as data.

Both the domain guard and the deterministic understanding path are driven by
these tables rather than by conditionals buried in code. Keeping them here means
a plant can extend the vocabulary — its own part-code shape, its own machine
naming, its own jargon — without touching the logic that uses it.

The lists are deliberately conservative. A term earns its place only if it would
be odd outside a manufacturing conversation: "spindle" qualifies, "report" does
not.
"""

from __future__ import annotations

import re

# Entity shapes. The guard runs before any database access (FR-9), so it
# recognises entities by pattern; exact ids are checked later against the MES.
MACHINE_ID_PATTERN = re.compile(r"\bCNC[-\s]?\d{1,3}\b", re.IGNORECASE)
PART_ID_PATTERN = re.compile(r"\b[A-Z]\d{2}\b")
MATERIAL_ID_PATTERN = re.compile(r"\b[A-Z]{2,6}-[A-Z0-9]{3,8}\b")

# Vocabulary that puts a request inside the industrial domain.
DOMAIN_TERMS: frozenset[str] = frozenset(
    {
        "cnc",
        "machine",
        "machines",
        "lathe",
        "mill",
        "milling",
        "spindle",
        "tool changer",
        "tooling",
        "coolant",
        "chuck",
        "fixture",
        "shop floor",
        "factory",
        "plant",
        "mes",
        "production",
        "produce",
        "producing",
        "produced",
        "output",
        "throughput",
        "capacity",
        "quantity",
        "units",
        "parts",
        "part",
        "batch",
        "job",
        "run",
        "manufacture",
        "manufacturing",
        "machining",
        "cycle time",
        "takt",
        "yield",
        "scrap",
        "reject",
        "rejects",
        "rejection",
        "rework",
        "defect",
        "quality",
        "maintenance",
        "service",
        "servicing",
        "inspection",
        "overhaul",
        "breakdown",
        "downtime",
        "uptime",
        "failure",
        "fault",
        "vibration",
        "temperature",
        "sensor",
        "condition",
        "health",
        "wear",
        "shift",
        "shifts",
        "schedule",
        "scheduled",
        "planned",
        "plan",
        "availability",
        "available",
        "utilisation",
        "utilization",
        "oee",
        "bottleneck",
        "constraint",
        "limiting",
        "capacity constraint",
        "inventory",
        "stock",
        "material",
        "materials",
        "raw material",
        "steel",
        "aluminium",
        "aluminum",
        "bronze",
        "billet",
        "bar",
        "blank",
        "reorder",
        "consumption",
        "order",
        "orders",
        "work order",
        "production order",
        "due date",
        "backlog",
        "shortfall",
        "underperformance",
        "output was",
        "target",
    }
)

# A part code alone is not proof of a factory question — "B12" could be a
# vitamin. It counts as an in-domain signal only next to one of these, which is
# also exactly the context in which a part code should be extracted, so both the
# guard and the rule-based extractor read the list from here.
PART_CONTEXT_TERMS: frozenset[str] = frozenset(
    {
        "part",
        "parts",
        "produce",
        "production",
        "produced",
        "make",
        "made",
        "how many",
        "capacity",
        "output",
        "quantity",
        "units",
        "order",
        "orders",
        "batch",
        "bottleneck",
        "limit",
        "limiting",
        "constrain",
        "slowing",
        "slow",
        "down",
        "lower",
        "shortfall",
        "reject",
        "scrap",
        "yesterday",
        "plan",
        "cycle time",
    }
)

# Requests that are clearly outside the industrial domain. Phrases, not bare
# words, because single words overlap with legitimate factory language:
# "stock" is inventory, "run" is a production run, "report" is a normal ask.
OUT_OF_DOMAIN_PHRASES: tuple[str, ...] = (
    "write a poem",
    "write me a poem",
    "poem about",
    "write a story",
    "write me a story",
    "tell me a story",
    "short story",
    "write a song",
    "song about",
    "write a novel",
    "lyrics",
    "haiku",
    "tell me a joke",
    "tell a joke",
    "make me laugh",
    "recipe",
    "how to cook",
    "what should i eat",
    "restaurant",
    "weather",
    "forecast for",
    "temperature outside",
    "translate",
    "in french",
    "in spanish",
    "in japanese",
    "capital of",
    "who is the president",
    "who won",
    "football",
    "soccer",
    "movie",
    "film recommendation",
    "tv show",
    "horoscope",
    "astrology",
    "share price",
    "stock price",
    "stock market",
    "bitcoin",
    "crypto",
    "medical advice",
    "diagnose me",
    "legal advice",
    "write code",
    "python script",
    "sql query",
    "javascript",
)

# Wording that signals each intent. Order matters: the first table whose
# patterns match wins, so the more specific questions are checked first.
# "Why was A12 production lower" contains "production" — analysis must be tried
# before capacity, or every past-tense question becomes a capacity request.
INTENT_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "production_analysis",
        (
            r"\bwhy\b.*\b(lower|low|below|down|drop|dropped|less|fell|short|miss|missed)\b",
            r"\b(shortfall|underperform|under-?performance)\b",
            r"\bplan vs\.? actual\b",
            r"\bactual vs\.? plan\b",
            r"\bexplain\b.*\b(yesterday|shortfall|drop|dip|miss)\b",
            r"\b(yesterday|last night)\b.*\b(why|lower|down|problem)\b",
        ),
    ),
    (
        "bottleneck",
        (
            r"\bbottleneck\b",
            r"\blimit(ing|s|ed)?\b",
            r"\bconstrain(ing|s|t|ts|ed)?\b",
            r"\bslow(ing|s|ed)? (down|us|it|production)\b",
            r"\bholding (us |it )?back\b",
            r"\bwhat'?s slowing\b",
            r"\bcapacity constraint\b",
        ),
    ),
    (
        "maintenance_attention",
        (
            r"\bmaintenance (attention|priorit|needed|required)\b",
            r"\bneeds? (maintenance|service|servicing|attention|inspection)\b",
            r"\bneeding (service|maintenance|attention)\b",
            r"\b(which|any|what) (machine|cnc|equipment).*"
            r"\b(unhealthy|attention|service|maintenance|problem)\b",
            r"\blooks? (unhealthy|bad|off)\b",
            r"\bmaintenance priorities\b",
        ),
    ),
    (
        "machine_health",
        (
            r"\bcan\b.*\b(continue|keep|carry on|still)\b.*\b(produc|run|operat)\w*",
            r"\bsafe to (run|operate|use)\b",
            r"\bok(ay)? (today|to run|right now)\b",
            r"\bshould i keep\b.*\bin production\b",
            r"\bfit to run\b",
            r"\bis\b.*\b(healthy|alright|fine)\b",
        ),
    ),
    (
        "production_capacity",
        (
            r"\bhow many\b",
            r"\bhow much\b.*\b(produce|output|make)\b",
            r"\bcapacity\b",
            r"\bmax(imum)?\b.*\b(quantity|output|production|units|parts)\b",
            r"\boutput potential\b",
            r"\bcan we (produce|make|run|build)\b",
            r"\bhow many can\b",
            r"\bproduction potential\b",
        ),
    ),
    (
        "machine_status",
        (
            r"\bstatus\b",
            r"\bwhat is\b.*\bdoing\b",
            r"\bcurrent (state|condition|job)\b",
            r"\bshow me\b.*\b(cnc|machine)\b",
            r"\bis .* (running|idle|stopped)\b",
        ),
    ),
    (
        "production_orders",
        (
            r"\b(production )?orders?\b",
            r"\bwork order\b",
            r"\bdue (date|this|next)\b",
            r"\bbacklog\b",
            r"\bwhat'?s planned\b",
            # A "planned quantity" question is an order lookup, not a capacity
            # calculation — the planned number lives in production_orders.
            r"\bplanned\b.*\b(quantity|production|output|amount)\b",
            r"\bhow many\b.*\bplanned\b",
            r"\bsupposed to (produce|make)\b",
        ),
    ),
    (
        "material_inventory",
        (
            r"\binventory\b",
            r"\bstock\b",
            r"\bhow much (material|steel|aluminium|aluminum)\b",
            r"\bmaterial (level|availability|on hand)\b",
            r"\breorder\b",
        ),
    ),
)

# Time expressions, longest first so "this week" is not shadowed by "week".
TIME_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bthe rest of (the |this )?week\b", "this_week"),
    (r"\bthis week\b", "this_week"),
    (r"\bwhole week\b", "full_week"),
    (r"\bentire week\b", "full_week"),
    (r"\bnext week\b", "next_week"),
    (r"\blast week\b", "last_week"),
    (r"\bby sunday\b", "this_week"),
    (r"\bby the end of the week\b", "this_week"),
    (r"\byesterday\b", "yesterday"),
    (r"\btomorrow\b", "tomorrow"),
    (r"\btoday\b", "today"),
    (r"\bright now\b", "today"),
    (r"\bcurrently\b", "today"),
    (r"\blast (7|seven) days\b", "last_7_days"),
    (r"\blast (30|thirty) days\b", "last_30_days"),
    (r"\blast month\b", "last_30_days"),
    (r"\bthis month\b", "last_30_days"),
)

# Words that pin down which quantity a "how many" question means (scenario R2).
METRIC_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b(max(imum)?|capacity|potential|could|can we|feasible|possible)\b", "max_capacity"),
    (r"\b(planned|scheduled|target|supposed to|due)\b", "planned_production"),
    (r"\b(actual(ly)?|produced|made|output was|did we (make|produce))\b", "actual_production"),
)

# The default window per intent when the question does not name one.
DEFAULT_WINDOW_BY_INTENT: dict[str, str] = {
    "machine_status": "today",
    "machine_health": "today",
    "production_capacity": "this_week",
    "bottleneck": "this_week",
    "production_analysis": "yesterday",
    "maintenance_attention": "today",
    "production_orders": "this_week",
    "material_inventory": "today",
}


def find_domain_signals(text: str) -> list[str]:
    """Every in-domain signal the text contains: entity shapes and vocabulary."""
    lowered = text.lower()
    signals: list[str] = []
    if MACHINE_ID_PATTERN.search(text):
        signals.append("machine id")
    if PART_ID_PATTERN.search(text.upper()) and any(term in lowered for term in PART_CONTEXT_TERMS):
        signals.append("part id")
    signals.extend(term for term in DOMAIN_TERMS if term in lowered)
    return signals


def find_out_of_domain_phrases(text: str) -> list[str]:
    lowered = text.lower()
    return [phrase for phrase in OUT_OF_DOMAIN_PHRASES if phrase in lowered]
