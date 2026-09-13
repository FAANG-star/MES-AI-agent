import type { ExecutedStep, PlannedToolCall, StepKind, StepStatus } from "./types";

/**
 * What the "AI Analysis Steps" panel renders, at any moment during a run.
 *
 * A planned step that has not run yet is `pending` — which is the panel's
 * reason for existing. The plan is produced before anything executes, so the
 * manager sees *what the agent intends to do* and then watches it happen,
 * rather than being shown a finished list afterwards and asked to believe it.
 */
export interface PanelStep {
  step: number;
  tool: string;
  kind: StepKind;
  title: string;
  status: StepStatus | "pending";
  summary: string;
  arguments: Record<string, unknown>;
  bindingNotes: string[];
  note: string | null;
  elapsed_ms: number;
  warnings: string[];
  missing: string[];
  sources: string[];
}

function fromPlan(planned: PlannedToolCall): PanelStep {
  return {
    step: planned.step,
    tool: planned.tool,
    kind: "tool",
    title: planned.title,
    status: "pending",
    summary: planned.reason,
    arguments: planned.arguments,
    // Before execution a binding is a promise: "machine_type comes from step 1".
    // After it, the executed step reports the value it actually resolved to.
    bindingNotes: planned.bindings.map(
      (b) => `${b.parameter} ← step ${b.from_step} · ${b.source_path}`,
    ),
    note: null,
    elapsed_ms: 0,
    warnings: [],
    missing: [],
    sources: [],
  };
}

function fromExecuted(step: ExecutedStep): PanelStep {
  return {
    step: step.step,
    tool: step.tool,
    kind: step.kind,
    title: step.title,
    status: step.status,
    summary: step.summary,
    arguments: step.arguments,
    bindingNotes: Object.entries(step.resolved_bindings).map(
      ([parameter, b]) => `${parameter} = ${JSON.stringify(b.value)} ← step ${b.from_step}`,
    ),
    note: step.note,
    elapsed_ms: step.elapsed_ms,
    warnings: step.warnings,
    missing: step.missing_fields.map((m) => m.field),
    sources: [...new Set(step.sources.map((s) => s.table))],
  };
}

/**
 * Merge the plan with whatever has executed so far.
 *
 * Executed steps win over planned ones with the same number. Steps beyond the
 * plan are appended: the engine, the explainer and the validator are not tool
 * calls and never appear in a plan, but they do appear in the trace — which is
 * why the hero run shows eight rows for a five-step plan.
 */
export function mergeSteps(plan: PlannedToolCall[], executed: ExecutedStep[]): PanelStep[] {
  const rows = new Map<number, PanelStep>();
  for (const planned of plan) rows.set(planned.step, fromPlan(planned));
  for (const step of executed) rows.set(step.step, fromExecuted(step));
  return [...rows.values()].sort((a, b) => a.step - b.step);
}

/** Controlled MES calls only — the figure the audit trail keeps. */
export function countToolCalls(steps: PanelStep[]): number {
  return steps.filter((s) => s.kind === "tool" && s.status === "ok").length;
}

/**
 * Where a run is, said in the manager's words — read from the events that
 * have actually arrived, never guessed from elapsed time.
 *
 * On CPU the two model calls are the slow parts: reading the question, then
 * writing the sentence. The MES calls between them take milliseconds. So the
 * stages are named for what is really being waited on.
 */
export type RunStage = "reading" | "querying" | "writing" | "done";

export function runStage(
  hasUnderstanding: boolean,
  steps: { kind: StepKind }[],
  hasAnswer: boolean,
): RunStage {
  if (hasAnswer) return "done";
  if (!hasUnderstanding) return "reading";
  // The engine step is the last thing before the explainer is called.
  return steps.some((s) => s.kind === "engine") ? "writing" : "querying";
}

export const STAGE_LABEL: Record<RunStage, string> = {
  reading: "Reading the question and planning the MES calls",
  querying: "Reading the MES through the controlled tools",
  writing: "Figures settled — writing the answer from them",
  done: "Done",
};
