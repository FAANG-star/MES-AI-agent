/**
 * The backend's shapes, mirrored.
 *
 * These types are a transcription of `backend/app/agent/schemas.py` and
 * `backend/app/engine/*`. They exist so the UI can render a run without
 * guessing, and so a field that disappears from the API becomes a TypeScript
 * error instead of an empty panel.
 *
 * Nothing here is computed. The UI displays what the run contains — the
 * headline figure, the bottleneck, the formula, the sources — and never adds
 * arithmetic of its own. That rule is the whole point of the architecture
 * behind it, and it does not stop at the API boundary.
 */

export type RunStatus =
  | "answered"
  | "clarify"
  | "refused_missing_data"
  | "rejected_out_of_domain"
  | "error";

export type StepStatus = "ok" | "not_implemented" | "skipped" | "failed";

/** 'tool' is a controlled MES call; 'engine' is deterministic Python; 'llm' is prose. */
export type StepKind = "tool" | "engine" | "llm";

export interface ResolvedWindow {
  label: string;
  start: string;
  end: string;
  days: number;
  timezone: string;
  basis: string;
}

export interface SourceRef {
  table: string;
  fields: string[];
  keys: string[];
  rows: number;
}

export interface MissingField {
  entity: string | null;
  field: string;
  reason: string;
}

export interface ResolvedBinding {
  value: unknown;
  from_step: number;
  source_path: string;
}

export interface ExecutedStep {
  step: number;
  tool: string;
  kind: StepKind;
  title: string;
  status: StepStatus;
  arguments: Record<string, unknown>;
  resolved_bindings: Record<string, ResolvedBinding>;
  summary: string;
  sources: SourceRef[];
  missing_fields: MissingField[];
  not_found: string[];
  warnings: string[];
  elapsed_ms: number;
  note: string | null;
}

export interface Headline {
  label: string;
  value: number | null;
  unit: string;
  /** Used when the answer is a name or a verdict rather than a number. */
  text: string | null;
}

export interface Bottleneck {
  machine_id: string;
  reason: string;
}

export interface Validation {
  grounded: boolean;
  retries: number;
  note: string;
}

export interface MachineCapacityLine {
  machine_id: string;
  status: string;
  eligible: boolean;
  ineligible_reason: string | null;
  planned_hours: number;
  maintenance_hours: number;
  effective_hours: number;
  parts_possible: number;
}

export interface CapacityResult {
  part_id: string;
  window: ResolvedWindow | null;
  cycle_time_min: number;
  required_machine_type: string;
  machines: MachineCapacityLine[];
  eligible_machine_ids: string[];
  total_effective_hours: number;
  machine_capacity: number;
  material_id: string | null;
  material_qty_per_unit: number | null;
  available_quantity: number | null;
  material_capacity: number | null;
  final_capacity: number;
  binding_constraint: "machine" | "material";
  /** The arithmetic, line by line, straight from the engine. */
  formula: string[];
}

export interface BottleneckFinding {
  machine_id: string;
  effective_hours: number;
  planned_hours: number;
  maintenance_hours: number;
  parts_possible: number;
  cause: string;
  margin_hours: number;
}

export interface ConstraintFinding {
  kind: "machine" | "material" | "none";
  bottleneck: BottleneckFinding | null;
  material_id: string | null;
  material_capacity: number | null;
  explanation: string;
  ranking: BottleneckFinding[];
}

export type ThresholdLevel = "normal" | "warning" | "critical" | "not_assessable";

export interface ThresholdCheck {
  rule_key: string;
  display_name: string;
  unit: string;
  reading: number | null;
  warning_threshold: number | null;
  critical_threshold: number | null;
  level: ThresholdLevel;
  relative_breach: number | null;
  verdict: string;
}

export interface MachineHealth {
  machine_id: string;
  status: string;
  can_produce: boolean;
  reason: string;
  checks: ThresholdCheck[];
  breaches: number;
  worst_relative_breach: number | null;
  fully_assessable: boolean;
  attention_note: string | null;
}

export interface ContributingFactor {
  kind: "downtime" | "rejects" | "unexplained" | "offset";
  label: string;
  impact_parts: number;
  detail: string;
  machines: string[];
}

export interface MachineDelta {
  machine_id: string;
  planned_quantity: number;
  produced_quantity: number;
  delta: number;
  downtime_hours: number;
  downtime_reason: string | null;
}

export interface ProductionAnalysis {
  part_id: string | null;
  planned_quantity: number;
  produced_quantity: number;
  rejected_quantity: number;
  processed_quantity: number;
  downtime_hours: number;
  shortfall: number;
  pct_below_plan: number | null;
  reject_rate_pct: number | null;
  parts_lost_to_downtime: number | null;
  by_machine: MachineDelta[];
  factors: ContributingFactor[];
  summary: string;
}

export interface Clarification {
  question: string;
  options: string[];
  because: string;
}

export interface PlannedToolCall {
  step: number;
  tool: string;
  title: string;
  arguments: Record<string, unknown>;
  bindings: {
    parameter: string;
    from_step: number;
    source_path: string;
    description: string;
  }[];
  reason: string;
  requires: string[];
}

export interface AgentRun {
  run_id: string;
  status: RunStatus;
  question: string;
  rewritten_question: string | null;
  intent: string;
  metric: string;
  window: ResolvedWindow | null;
  answer: string;
  /** True when the local model wrote the prose; false is the deterministic fallback. */
  answer_is_generated: boolean;
  headline: Headline | null;
  bottleneck: Bottleneck | null;
  steps: ExecutedStep[];
  sources: SourceRef[];
  missing_fields: MissingField[];
  validation: Validation;
  capacity: CapacityResult | null;
  constraint: ConstraintFinding | null;
  health: MachineHealth[];
  analysis: ProductionAnalysis | null;
  clarification: Clarification | null;
  rejection: string | null;
  notes: string[];
  elapsed_ms: number;
  /** Counted by the backend, so the screen and the audit trail cannot disagree. */
  tool_call_count: number;
}

// ----------------------------------------------------------------- machines

export interface MachineStatus {
  machine_id: string;
  machine_name: string;
  machine_type: string;
  status: "running" | "idle" | "maintenance" | "offline" | string;
  current_job: string | null;
  available_hours: number | null;
  temperature_c: number | null;
  vibration_mm_s: number | null;
  utilization_pct: number | null;
  last_reading_at: string | null;
}

export interface RuleThreshold {
  rule_key: string;
  display_name: string;
  unit: string;
  warning_threshold: number | null;
  critical_threshold: number | null;
  comparison: string;
  notes: string | null;
}

export interface MachineStatusEnvelope {
  ok: boolean;
  data: { machines: MachineStatus[]; thresholds?: RuleThreshold[] };
}

export interface Health {
  status: string;
  database: { connected: boolean; user: string; read_only: boolean; machines: number };
  /** `pinned` is true during a rehearsal (FACTORY_TODAY set on the backend). */
  factory: { timezone: string; today: string; now: string; pinned?: boolean };
  tools: { total: number; implemented: number };
  /**
   * What the backend actually sends. The top bar once compared this with
   * "rules", which the backend never sends, so degraded mode was reported as
   * "Local model" — see `agentMode`.
   */
  agent: { llm_provider: string; llm_available: boolean; understanding: "llm" | "deterministic_rules" | string };
}

// ------------------------------------------------------------ stream events

export interface AcceptedEvent {
  run_id: string;
  question: string;
}

export interface UnderstandingEvent {
  run_id: string;
  status: string;
  intent: string;
  metric: string;
  rewritten_question: string | null;
  window: ResolvedWindow | null;
  understood_by: "llm" | "rules";
  degraded: boolean;
  confidence: number;
  plan: PlannedToolCall[];
}

/** One executed step, plus how many steps the *plan* held (never the total). */
export type StepEvent = ExecutedStep & { run_id: string; planned_steps: number };

export interface AnswerEvent {
  run_id: string;
  answer: string;
  answer_is_generated: boolean;
  validation: Validation;
}
