"""Typed objects the understanding pipeline produces (FR-3).

Everything the language model contributes lands in one of these models. That is
the point: the model never hands back prose that later code has to interpret. If
it cannot fill the schema, the request becomes a clarification rather than a
guess.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, PrivateAttr, computed_field

from app.engine.analysis import ProductionAnalysis
from app.engine.bottleneck import ConstraintFinding
from app.engine.capacity import CapacityResult
from app.engine.rules import MachineHealth
from app.schemas.envelope import MissingField, SourceRef
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
    step 1" — and lets the executor run it without re-deriving anything.
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
    requires: list[str] = Field(
        default_factory=list,
        description=(
            "Fully qualified fields this step must come back with, e.g. 'parts.cycle_time_min'. "
            "If the tool reports one of them in missing_fields, the run refuses instead of "
            "continuing — which is FR-8 expressed as data rather than as a special case in code."
        ),
    )


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


class StepStatus(StrEnum):
    OK = "ok"
    NOT_IMPLEMENTED = "not_implemented"  # declared tool, not implemented yet
    SKIPPED = "skipped"  # an earlier step made this one pointless
    FAILED = "failed"


class RunStatus(StrEnum):
    ANSWERED = "answered"
    CLARIFY = "clarify"
    REFUSED_MISSING_DATA = "refused_missing_data"
    REJECTED_OUT_OF_DOMAIN = "rejected_out_of_domain"
    ERROR = "error"


class ExecutedStep(BaseModel):
    """One plan step after it ran — what the UI's analysis panel renders."""

    step: int
    tool: str
    kind: str = Field(
        default="tool",
        description=(
            "'tool' for a controlled MES call, 'engine' for a deterministic calculation or "
            "rule check. Only 'tool' steps count as tool calls in the audit trail."
        ),
    )
    title: str
    status: StepStatus
    arguments: dict = Field(
        default_factory=dict, description="Arguments actually sent, after bindings were resolved"
    )
    resolved_bindings: dict = Field(
        default_factory=dict,
        description="Which value each binding produced, and which step it came from",
    )
    summary: str = Field(default="", description="One line a factory manager can read")
    sources: list[SourceRef] = Field(default_factory=list)
    missing_fields: list[MissingField] = Field(default_factory=list)
    not_found: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    detail: dict | None = Field(
        default=None, description="The tool's full envelope, for the trace and the debug view"
    )
    elapsed_ms: int = 0
    note: str | None = None

    # The typed tool result, kept for the engine but never serialised: the
    # envelope is already in `detail`, and duplicating it would double the
    # size of every trace.
    _typed: object | None = PrivateAttr(default=None)


class Headline(BaseModel):
    """The one thing the answer card leads with."""

    label: str
    value: float | int | None = None
    unit: str = ""
    text: str | None = Field(
        default=None, description="Used when the headline is a name rather than a number"
    )


class Bottleneck(BaseModel):
    machine_id: str
    reason: str


class Validation(BaseModel):
    grounded: bool = True
    retries: int = 0
    note: str = ""


class AgentRun(BaseModel):
    """The complete, structured result of one question (docs/02 §7).

    Everything the UI needs and everything the audit trail keeps: what was asked,
    how it was read, every step that ran, every source touched, and why the run
    ended the way it did.
    """

    run_id: str
    status: RunStatus
    question: str
    rewritten_question: str | None = None
    intent: Intent = Intent.UNKNOWN
    metric: Metric = Metric.NONE
    window: ResolvedWindow | None = None
    answer: str = ""
    answer_is_generated: bool = Field(
        default=False,
        description=(
            "False while the answer is assembled deterministically; "
            "the explainer sets it true once its wording has been validated"
        ),
    )
    headline: Headline | None = None
    bottleneck: Bottleneck | None = None
    steps: list[ExecutedStep] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    missing_fields: list[MissingField] = Field(default_factory=list)
    validation: Validation = Field(default_factory=Validation)

    # What the deterministic engine produced, typed so the UI and the tests can
    # read it without parsing prose. Populated per intent; the rest stay unset.
    capacity: CapacityResult | None = None
    constraint: ConstraintFinding | None = None
    health: list[MachineHealth] = Field(default_factory=list)
    analysis: ProductionAnalysis | None = None
    clarification: Clarification | None = None
    rejection: str | None = None
    understanding: Understanding | None = None
    notes: list[str] = Field(default_factory=list)
    elapsed_ms: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tool_call_count(self) -> int:
        """Controlled MES calls only — engine steps are calculations, not calls.

        Serialised, so the UI displays the number the backend counted rather
        than recounting the steps itself. The audit trail and the screen cannot
        disagree about how many times the factory was read.
        """
        return sum(1 for s in self.steps if s.status is StepStatus.OK and s.kind == "tool")


class Understanding(BaseModel):
    """Everything understanding produces for one question. The executor runs the plan."""

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


# AgentRun refers to Understanding, which is defined below it: the run is the
# outer object but the reading comes first in the story the file tells.
AgentRun.model_rebuild()
ExecutedStep.model_rebuild()
