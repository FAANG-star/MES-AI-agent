/**
 * Presentation helpers. Formatting only — never arithmetic.
 *
 * Every number on screen arrives from the engine already final. These
 * functions choose how it is written, not what it is.
 */

import type { SourceRef, StepKind, ThresholdLevel } from "./types";

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

/**
 * Factory-local wall clock, taken from the string as sent.
 *
 * The backend stamps its own offset (`…T12:28:34+09:00`). Parsing it into a
 * `Date` and formatting would re-express it in the *viewer's* timezone, so a
 * manager in Tokyo and a reviewer in Berlin would see two different factory
 * clocks. The factory has one.
 */
export function factoryTime(iso: string): string {
  const match = /T(\d{2}):(\d{2})/.exec(iso);
  return match ? `${match[1]}:${match[2]}` : "";
}

export function factoryDate(iso: string): string {
  return iso.slice(0, 10);
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

export const LEVEL_TONE: Record<ThresholdLevel, string> = {
  normal: "text-emerald-700 bg-emerald-50 ring-emerald-600/20",
  warning: "text-amber-800 bg-amber-50 ring-amber-600/25",
  critical: "text-red-800 bg-red-50 ring-red-600/25",
  not_assessable: "text-slate-600 bg-slate-100 ring-slate-500/20",
};

export const MACHINE_TONE: Record<string, string> = {
  running: "text-emerald-700 bg-emerald-50 ring-emerald-600/20",
  idle: "text-sky-700 bg-sky-50 ring-sky-600/20",
  maintenance: "text-amber-800 bg-amber-50 ring-amber-600/25",
  offline: "text-slate-600 bg-slate-100 ring-slate-500/20",
};

export function machineTone(status: string): string {
  return MACHINE_TONE[status] ?? MACHINE_TONE.offline;
}

/**
 * How a reading compares with its limit — for colour only.
 *
 * The verdict itself is the engine's (`ThresholdCheck.level`); this is used on
 * the status strip, which shows raw sensor values with no run behind them.
 */
export function readingTone(reading: number | null, limit: number | null): string {
  if (reading === null) return "text-slate-400";
  if (limit === null) return "text-slate-700";
  return reading >= limit ? "text-red-600 font-semibold" : "text-slate-700";
}
