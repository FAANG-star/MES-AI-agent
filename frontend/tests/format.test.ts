import { describe, expect, it } from "vitest";

import {
  agentMode,
  describeSource,
  formatElapsed,
  formatHeadline,
  formatNumber,
  formatReading,
  formatWindow,
  headlineParts,
  headlineSize,
  humanise,
  readingLevel,
  sourceLabel,
} from "@/lib/format";

describe("formatting figures", () => {
  it("groups thousands the same way everywhere", () => {
    expect(formatNumber(1139)).toBe("1,139");
    expect(formatNumber(9600)).toBe("9,600");
  });

  it("leaves small numbers alone", () => {
    expect(formatNumber(8)).toBe("8");
    expect(formatNumber(0)).toBe("0");
  });

  it("keeps the decimals the factory uses", () => {
    expect(formatNumber(18.5)).toBe("18.5");
    expect(formatNumber(3.5)).toBe("3.5");
    expect(formatNumber(2.1)).toBe("2.1");
  });

  it("renders a headline as a figure, a name, or nothing at all", () => {
    expect(formatHeadline(1139, "units", null)).toBe("1,139 units");
    expect(formatHeadline(14, "%", null)).toBe("14 %");
    // S5's headline is a machine; S2's is a verdict. Neither is a number.
    expect(formatHeadline(null, "", "CNC-04")).toBe("CNC-04");
    expect(formatHeadline(null, "units", null)).toBe("—");
  });

  it("says 'no reading' rather than zero", () => {
    // CNC-02's vibration sensor is offline. Zero would be a factory claim.
    expect(formatReading(null, "mm/s")).toBe("no reading");
    expect(formatReading(1.8, "mm/s")).toBe("1.8 mm/s");
  });

  it("writes elapsed time at a readable scale", () => {
    expect(formatElapsed(3)).toBe("3 ms");
    expect(formatElapsed(37842)).toBe("37.8 s");
  });
});

describe("the window", () => {
  it("describes a window by its dates and length", () => {
    expect(formatWindow("2026-09-12", "2026-09-13", 2)).toBe("2026-09-12 → 2026-09-13 (2 days)");
    expect(formatWindow("2026-09-11", "2026-09-11", 1)).toBe("2026-09-11 (1 day)");
  });
});

describe("the Data Used panel", () => {
  it("names tables the way a factory manager would", () => {
    expect(sourceLabel("machine_shift_calendar")).toBe("Machine availability");
    expect(sourceLabel("parts")).toBe("Cycle time and routing");
    expect(sourceLabel("rule_thresholds")).toBe("Factory condition limits");
  });

  it("falls back to the table's own name rather than hiding it", () => {
    expect(sourceLabel("some_new_table")).toBe("some_new_table");
  });

  it("summarises which records were read", () => {
    expect(
      describeSource({ table: "parts", fields: ["cycle_time_min"], keys: ["A12"], rows: 1 }),
    ).toBe("A12 · 1 row");

    expect(describeSource({ table: "machines", fields: [], keys: [], rows: 5 })).toBe(
      "all records · 5 rows",
    );
  });
});

describe("placing a live reading against its limit", () => {
  it("marks a reading at or over the limit", () => {
    expect(readingLevel(72.5, 70)).toBe("at_limit");
    expect(readingLevel(3.1, 2.5)).toBe("at_limit");
    expect(readingLevel(70, 70)).toBe("at_limit");
  });

  it("leaves a reading under the limit alone", () => {
    expect(readingLevel(52, 70)).toBe("within");
  });

  it("does not call a missing reading within the limit", () => {
    // CNC-02's vibration sensor is offline. "Within" would be a factory claim.
    expect(readingLevel(null, 2.5)).toBe("unknown");
  });

  it("has nothing to compare against when no limit exists", () => {
    expect(readingLevel(88.1, null)).toBe("within");
  });
});

describe("the headline", () => {
  it("splits a figure from its unit so the unit can be set smaller", () => {
    expect(headlineParts(1139, "units", null)).toEqual({ figure: "1,139", unit: "units" });
    expect(headlineParts(14, "%", null)).toEqual({ figure: "14", unit: "%" });
  });

  it("shows a name or verdict whole", () => {
    expect(headlineParts(null, "", "CNC-04")).toEqual({ figure: "CNC-04", unit: "" });
  });

  it("never invents a figure", () => {
    expect(headlineParts(null, "units", null)).toEqual({ figure: "—", unit: "" });
  });

  it("reads identifiers as words", () => {
    expect(humanise("production_capacity")).toBe("production capacity");
  });
});

describe("the model indicator", () => {
  const health = (understanding: string) =>
    ({
      status: "ok",
      database: { connected: true, user: "mes_ro", read_only: true, machines: 5 },
      factory: { timezone: "Asia/Tokyo", today: "2026-09-14", now: "2026-09-14T09:00:00+09:00" },
      tools: { total: 8, implemented: 8 },
      agent: { llm_provider: "openai_compatible", llm_available: understanding === "llm", understanding },
    }) as const;

  it("reports the local model only when the backend says so", () => {
    expect(agentMode(health("llm"))).toBe("llm");
  });

  it("reports rules for what the backend actually sends in degraded mode", () => {
    // The regression: this value was compared against "rules" and fell through
    // to "Local model".
    expect(agentMode(health("deterministic_rules"))).toBe("rules");
  });

  it("fails towards the honest label for anything unexpected", () => {
    expect(agentMode(health("something_new"))).toBe("rules");
    expect(agentMode(null)).toBe("unknown");
  });
});

describe("headline size", () => {
  it("keeps a figure as large as it is now", () => {
    expect(headlineSize("3,770")).toContain("72px");
    expect(headlineSize("CNC-03")).toContain("72px");
  });

  it("steps a worded headline down so it reads as one statement", () => {
    // "Which machine limits a material-bound part?" has no machine to name.
    expect(headlineSize("No single machine — material-limited")).toContain("32px");
    expect(headlineSize("Can continue production")).toContain("32px");
  });
});
