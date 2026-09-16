/**
 * Presentation helpers. Formatting only — never arithmetic.
 *
 * Every number on screen arrives from the engine already final. These
 * functions choose how it is written, not what it is.
 */

import type { Health, SourceRef, StepKind } from "./types";

/**
 * Group digits the same way on every machine.
 *
 * The browser's own locale is deliberately not used: the demo laptop and the
 * developer's machine must render "1,139" identically, and a run that reads
 * differently in two places is the one thing this project refuses to ship.
 */
const GROUPED = new Intl.NumberFormat("en-US");

export function formatNumber(value: number): string {
  return Number.isInteger(value) ? GROUPED.format(value) : GROUPED.format(round(value, 2));
}

function round(value: number, dp: number): number {
  const factor = 10 ** dp;
  return Math.round(value * factor) / factor;
}

/** "1,139 units" · "14 %" · "CNC-04" — whatever the headline actually holds. */
export function formatHeadline(value: number | null, unit: string, text: string | null): string {
  if (text) return text;
  if (value === null) return "—";
  return unit ? `${formatNumber(value)} ${unit}` : formatNumber(value);
}

export function formatHours(hours: number): string {
  return `${formatNumber(hours)} h`;
}

export function formatReading(reading: number | null, unit: string): string {
  return reading === null ? "no reading" : `${formatNumber(reading)} ${unit}`;
}

export function formatElapsed(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

/** "2026-09-12 → 2026-09-13 (2 days)" */
export function formatWindow(start: string, end: string, days: number): string {
  const span = days === 1 ? "1 day" : `${days} days`;
  return start === end ? `${start} (${span})` : `${start} → ${end} (${span})`;
}

// ------------------------------------------------------------ "Data Used"

/**
 * What a table means to a factory manager.
 *
 * The requirement's mock shows "Machine availability · Cycle time ·
 * Maintenance · Inventory", not a list of table names. The mapping is fixed
 * here rather than generated, so the wording is reviewable; an unmapped table
 * falls back to its own name rather than being hidden.
 */
const SOURCE_LABELS: Record<string, string> = {
  machines: "Machine status",
  machine_shift_calendar: "Machine availability",
  parts: "Cycle time and routing",
  inventory: "Material inventory",
  maintenance: "Maintenance schedule",
  production_orders: "Production orders",
  production_history: "Production history",
  rule_thresholds: "Factory condition limits",
};

export function sourceLabel(table: string): string {
  return SOURCE_LABELS[table] ?? table;
}

export function describeSource(source: SourceRef): string {
  const keys = source.keys.length ? source.keys.join(", ") : "all records";
  const rows = source.rows === 1 ? "1 row" : `${source.rows} rows`;
  return `${keys} · ${rows}`;
}

// --------------------------------------------------------------- step kinds

/**
 * What each kind of step is, said plainly.
 *
 * The distinction is the demo's central claim — the model chose the questions,
 * Python produced the numbers — so the panel labels it on every row instead of
 * leaving the viewer to infer it.
 */
export const STEP_KIND: Record<StepKind, { label: string; hint: string }> = {
  tool: { label: "MES tool", hint: "A controlled read of the factory database." },
  engine: { label: "Calculation", hint: "Deterministic Python. No language model." },
  llm: { label: "Language model", hint: "Phrasing only. It is given the figures." },
};

/**
 * How a live reading sits against the limit the MES supplied.
 *
 * Used by the machine strip, which shows raw sensor values with no run behind
 * them — so this decides a colour, never a verdict. Whether a machine may keep
 * running is the rule engine's call, made inside an answer with the limit cited.
 */
export type ReadingLevel = "unknown" | "within" | "at_limit";

export function readingLevel(reading: number | null, limit: number | null): ReadingLevel {
  if (reading === null) return "unknown";
  if (limit === null) return "within";
  return reading >= limit ? "at_limit" : "within";
}

/**
 * A headline split into its figure and its unit, so the unit can be set
 * smaller than the number it qualifies. Formatting only: the figure is the one
 * the engine returned.
 */
export function headlineParts(
  value: number | null,
  unit: string,
  text: string | null,
): { figure: string; unit: string } {
  if (text) return { figure: text, unit: "" };
  if (value === null) return { figure: "—", unit: "" };
  return { figure: formatNumber(value), unit };
}

/**
 * How large the headline is set.
 *
 * A figure is the loudest thing on the page, and "3,770" stays that way. A
 * headline that is words — a machine id, a verdict, "No single machine —
 * material-limited" — needs the size stepped down or it wraps across three
 * lines and stops reading as one statement.
 */
export function headlineSize(figure: string): string {
  if (figure.length <= 8) return "text-[56px] sm:text-[72px] tracking-[-0.045em]";
  if (figure.length <= 22) return "text-[38px] sm:text-[48px] tracking-[-0.035em]";
  return "text-[26px] sm:text-[32px] tracking-[-0.02em]";
}

/**
 * Whether the factory data still describes today, said in a few words.
 *
 * The seeded week is laid out around whatever "today" was when it was seeded,
 * so a database from yesterday keeps answering — consistently, and about
 * yesterday. The backend measures it; this decides what the top bar says.
 */
export function datasetWarning(health: Health | null): string | null {
  const dataset = health?.dataset;
  if (!dataset || dataset.fresh) return null;
  if (dataset.last_production_day === null) return "No factory data";
  if (dataset.stale_days < 0) return "Data ahead of today";
  return dataset.stale_days === 1 ? "Data 1 day old" : `Data ${dataset.stale_days} days old`;
}

/** "production_capacity" → "production capacity" */
export function humanise(identifier: string): string {
  return identifier.replaceAll("_", " ");
}

/**
 * Whether the local model is doing the understanding, or the rules are.
 *
 * Anything other than an explicit "llm" is treated as degraded. Found in testing:
 * the check compared against "rules" while the backend sends
 * "deterministic_rules", so a stack with no model reachable told the factory
 * manager "Local model". Failing towards the honest label is the only safe
 * direction for an indicator whose whole job is honesty.
 */
export function agentMode(health: Health | null): "llm" | "rules" | "unknown" {
  if (!health) return "unknown";
  return health.agent.understanding === "llm" ? "llm" : "rules";
}
