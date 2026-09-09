"""Typed objects the understanding pipeline produces (FR-3).

Everything the language model contributes lands in one of these models. That is
the point: the model never hands back prose that later code has to interpret. If
it cannot fill the schema, the request becomes a clarification rather than a
guess.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from app.timewindow import ResolvedWindow


class Intent(StrEnum):
    """What the factory manager is asking for.

    One value per demo scenario, plus two straightforward lookups and `unknown`,
    which always routes to a clarifying question instead of a plan.
    """

    MACHINE_STATUS = "machine_status"  # Demo 1 — what is CNC-03 doing
    MACHINE_HEALTH = "machine_health"  # S2 — can it keep running
    PRODUCTION_CAPACITY = "production_capacity"  # S1 — the hero scenario
    BOTTLENECK = "bottleneck"  # S3 — what limits a part
    PRODUCTION_ANALYSIS = "production_analysis"  # S4 — why was output low
    MAINTENANCE_ATTENTION = "maintenance_attention"  # S5 — what needs service
    PRODUCTION_ORDERS = "production_orders"  # what is planned
    MATERIAL_INVENTORY = "material_inventory"  # what stock is on hand
    UNKNOWN = "unknown"


class Metric(StrEnum):
    """Which quantity a "how many" question means — the R2 ambiguity axis."""

    MAX_CAPACITY = "max_capacity"
    PLANNED_PRODUCTION = "planned_production"
    ACTUAL_PRODUCTION = "actual_production"
    STATUS = "status"
    NONE = "none"


class UnderstandingStatus(StrEnum):
    UNDERSTOOD = "understood"
    CLARIFY = "clarify"
    REJECTED_OUT_OF_DOMAIN = "rejected_out_of_domain"


class ExtractedIntent(BaseModel):
    """The schema the language model fills in — one call, one object.

    Rewrite and intent are produced together on purpose: extracted separately
    they can disagree, and a rewrite that contradicts the intent behind it is
    worse than no rewrite at all.
    """

    rewritten_question: str = Field(
        description=(
            "The question restated as a complete, unambiguous factory request. Keep the "
            "manager's meaning; add only what was implied, never new entities or numbers."
        )
    )
    intent: Intent = Field(description="Which kind of factory question this is.")
    metric: Metric = Field(
        default=Metric.NONE,
        description=(
            "For quantity questions: maximum feasible capacity, the planned quantity, or "
            "what was actually produced. Use 'none' when the question is not about a quantity."
        ),
    )
    part_ids: list[str] = Field(
        default_factory=list, description="Part ids mentioned, e.g. ['A12']."
    )
    machine_ids: list[str] = Field(
        default_factory=list, description="Machine ids mentioned, e.g. ['CNC-03']."
    )
    material_ids: list[str] = Field(default_factory=list, description="Material ids mentioned.")
    time_window: str = Field(
        default="this_week",
        description=(
            "One of: today, tomorrow, yesterday, this_week, full_week, next_week, last_week, "
            "last_7_days, last_30_days; or an ISO date; or an ISO range 'start..end'."
        ),
    )
    required_tools: list[str] = Field(
        default_factory=list,
        description=(
            "Names of the MES tools needed to answer. Use only names from the supplied catalogue."
        ),
    )
    ambiguous: bool = Field(
        default=False,
        description=(
            "True when the question could mean materially different things and must be clarified."
        ),
    )
    ambiguity_reason: str | None = Field(
        default=None, description="What is unclear, in one sentence."
    )
    clarification_options: list[str] = Field(
        default_factory=list,
        description="Two to four concrete readings the manager can choose between.",
    )
    confidence: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Confidence in this reading, 0 to 1."
    )
    reasoning: str = Field(default="", description="One sentence on how the reading was reached.")


class EntityRef(BaseModel):
    """An entity named in the question, checked against the real MES."""

    id: str
    kind: str  # part | machine | material
    exists: bool
    name: str | None = None


class ResolvedEntities(BaseModel):
    parts: list[EntityRef] = Field(default_factory=list)
    machines: list[EntityRef] = Field(default_factory=list)
    materials: list[EntityRef] = Field(default_factory=list)
    unknown: list[EntityRef] = Field(default_factory=list)
    known_part_ids: list[str] = Field(default_factory=list)
    known_machine_ids: list[str] = Field(default_factory=list)

    @property
    def has_unknown(self) -> bool:
        return bool(self.unknown)


class ArgumentBinding(BaseModel):
    """An argument that only exists once an earlier step has run.

    Declaring the dependency instead of resolving it now keeps the plan
    inspectable before execution — the UI can show step 2 as "machine type from
    step 1" — and lets Day 5 execute it without re-deriving anything.
    """

    parameter: str
    from_step: int
    source_path: str = Field(
        description="Dotted path into the earlier tool result, e.g. 'data.part.material_id'"
    )
    description: str


class PlannedToolCall(BaseModel):
    step: int
    tool: str
    title: str = Field(description="Human-readable step title for the AI Analysis Steps panel")
    arguments: dict = Field(default_factory=dict)
    bindings: list[ArgumentBinding] = Field(default_factory=list)
    reason: str = Field(description="Why this tool is needed for this question")


class Clarification(BaseModel):
    question: str
    options: list[str] = Field(default_factory=list)
    because: str


class GuardVerdict(BaseModel):
    """Result of the industrial-domain check (FR-9), run before anything else."""

    in_domain: bool
    decided_by: str  # denylist | allowlist | llm | fail_closed
    reason: str
    matched_signals: list[str] = Field(default_factory=list)


class DomainClassification(BaseModel):
    """Schema for the guard's optional LLM second opinion."""

    in_domain: bool = Field(
        description=(
            "True only if the request concerns manufacturing, CNC machining, production, "
            "maintenance, materials, or the MES system itself."
        )
    )
    reason: str = Field(description="One short sentence explaining the decision.")


class Understanding(BaseModel):
    """Everything Day 4 produces for one question. Day 5 executes the plan."""

    status: UnderstandingStatus
    question: str
    rewritten_question: str | None = None
    intent: Intent = Intent.UNKNOWN
    metric: Metric = Metric.NONE
    entities: ResolvedEntities = Field(default_factory=ResolvedEntities)
    window: ResolvedWindow | None = None
    confidence: float = 0.0
    plan: list[PlannedToolCall] = Field(default_factory=list)
    clarification: Clarification | None = None
    rejection: str | None = None
    guard: GuardVerdict | None = None
    understood_by: str = Field(
        default="rules", description="llm | rules — which path produced the reading"
    )
    provider: str = Field(default="none", description="Which LLM provider answered, or 'none'")
    degraded: bool = Field(
        default=False,
        description="True when no language model was available and rules were used instead",
    )
    notes: list[str] = Field(default_factory=list)
    elapsed_ms: int = 0
