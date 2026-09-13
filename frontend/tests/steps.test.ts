import { describe, expect, it } from "vitest";

import { countToolCalls, mergeSteps } from "@/lib/steps";
import type { ExecutedStep, PlannedToolCall } from "@/lib/types";

function planned(step: number, tool: string, extra: Partial<PlannedToolCall> = {}) {
  return {
    step,
    tool,
    title: `Run ${tool}`,
    arguments: {},
    bindings: [],
    reason: "because the plan says so",
    requires: [],
    ...extra,
  } satisfies PlannedToolCall;
}

function executed(step: number, tool: string, extra: Partial<ExecutedStep> = {}) {
  return {
    step,
    tool,
    kind: "tool",
    title: `Run ${tool}`,
    status: "ok",
    arguments: {},
    resolved_bindings: {},
    summary: "it worked",
    sources: [],
    missing_fields: [],
    not_found: [],
    warnings: [],
    elapsed_ms: 1,
    note: null,
    ...extra,
  } satisfies ExecutedStep;
}

describe("merging the plan with what has run", () => {
  it("shows the whole plan as pending before anything executes", () => {
    const rows = mergeSteps([planned(1, "get_part_information"), planned(2, "get_available_machines")], []);

    expect(rows.map((r) => r.status)).toEqual(["pending", "pending"]);
    expect(rows[0].title).toBe("Run get_part_information");
  });

  it("replaces a planned step with the executed one", () => {
    const rows = mergeSteps(
      [planned(1, "get_part_information"), planned(2, "get_available_machines")],
      [executed(1, "get_part_information", { summary: "A12: 3.5 min/part." })],
    );

    expect(rows[0].status).toBe("ok");
    expect(rows[0].summary).toBe("A12: 3.5 min/part.");
    expect(rows[1].status).toBe("pending");
  });

  it("appends the steps that are not in any plan", () => {
    // The hero run: a five-step plan, eight rows. The engine, the explainer and
    // the validator are not tool calls, so they never appear in `plan`.
    const plan = [1, 2, 3, 4, 5].map((n) => planned(n, `tool_${n}`));
    const ran = [
      ...[1, 2, 3, 4, 5].map((n) => executed(n, `tool_${n}`)),
      executed(6, "calculation_engine", { kind: "engine" }),
      executed(7, "explainer", { kind: "llm" }),
      executed(8, "grounding_validator", { kind: "engine" }),
    ];

    const rows = mergeSteps(plan, ran);

    expect(rows).toHaveLength(8);
    expect(rows.map((r) => r.kind)).toEqual([
      "tool",
      "tool",
      "tool",
      "tool",
      "tool",
      "engine",
      "llm",
      "engine",
    ]);
  });

  it("orders rows by step number whatever order they arrived in", () => {
    const rows = mergeSteps([], [executed(3, "c"), executed(1, "a"), executed(2, "b")]);

    expect(rows.map((r) => r.step)).toEqual([1, 2, 3]);
  });

  it("turns a declared binding into a promise, and a resolved one into a value", () => {
    const plan = [
      planned(2, "get_available_machines", {
        bindings: [
          {
            parameter: "machine_type",
            from_step: 1,
            source_path: "data.part.required_machine_type",
            description: "the machine type A12 needs",
          },
        ],
      }),
    ];

    expect(mergeSteps(plan, [])[0].bindingNotes).toEqual([
      "machine_type ← step 1 · data.part.required_machine_type",
    ]);

    const ran = [
      executed(2, "get_available_machines", {
        resolved_bindings: {
          machine_type: {
            value: "CNC_LATHE",
            from_step: 1,
            source_path: "data.part.required_machine_type",
          },
        },
      }),
    ];

    expect(mergeSteps(plan, ran)[0].bindingNotes).toEqual([
      'machine_type = "CNC_LATHE" ← step 1',
    ]);
  });

  it("keeps a skipped step visible rather than dropping it", () => {
    // The refusal path marks the rest of the plan skipped. Hiding those rows
    // would hide the fact that nothing was computed.
    const rows = mergeSteps(
      [planned(1, "get_part_information"), planned(2, "calculate_production_capacity")],
      [executed(1, "get_part_information"), executed(2, "calculate_production_capacity", { status: "skipped" })],
    );

    expect(rows.map((r) => r.status)).toEqual(["ok", "skipped"]);
  });

  it("counts only successful MES calls as tool calls", () => {
    const rows = mergeSteps(
      [],
      [
        executed(1, "get_part_information"),
        executed(2, "get_available_machines", { status: "skipped" }),
        executed(3, "calculation_engine", { kind: "engine" }),
        executed(4, "explainer", { kind: "llm" }),
      ],
    );

    expect(countToolCalls(rows)).toBe(1);
  });
});
