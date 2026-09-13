import { describe, expect, it } from "vitest";

import {
  describeSource,
  factoryDate,
  factoryTime,
  formatElapsed,
  formatHeadline,
  formatNumber,
  formatReading,
  formatWindow,
  readingTone,
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

describe("the factory clock", () => {
  it("shows the factory's wall time, not the viewer's", () => {
    // Asia/Tokyo, read straight from the offset the backend sent. Converting
    // would show 03:28 to a reviewer in London and call it the factory's time.
    expect(factoryTime("2026-09-12T12:28:34.561211+09:00")).toBe("12:28");
    expect(factoryDate("2026-09-12T12:28:34.561211+09:00")).toBe("2026-09-12");
  });

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

describe("colouring a reading against its limit", () => {
  it("marks a reading at or over the limit", () => {
    expect(readingTone(72.5, 70)).toContain("red");
    expect(readingTone(3.1, 2.5)).toContain("red");
  });

  it("leaves a reading under the limit plain", () => {
    expect(readingTone(52, 70)).not.toContain("red");
  });

  it("says nothing about a reading that does not exist", () => {
    expect(readingTone(null, 70)).not.toContain("red");
  });
});
