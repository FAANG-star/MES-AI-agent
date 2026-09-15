import { describe, expect, it } from "vitest";

import {
  conditionRows,
  machineMaintenance,
  machineTypeLabel,
  maintenanceKind,
  statusNote,
} from "@/lib/machines";
import type { FactoryMaintenance, MachineStatus, MaintenanceEvent, RuleThreshold } from "@/lib/types";

const CNC01: MachineStatus = {
  machine_id: "CNC-01",
  machine_name: "CNC Lathe 01",
  machine_type: "CNC_LATHE",
  status: "running",
  current_job: "PO-1002",
  available_hours: null,
  temperature_c: 72.5,
  vibration_mm_s: 1.2,
  utilization_pct: 84.2,
  last_reading_at: "2026-09-15T02:00:00+00:00",
};

const CNC02: MachineStatus = {
  ...CNC01,
  machine_id: "CNC-02",
  machine_name: "CNC Lathe 02",
  temperature_c: 61,
  vibration_mm_s: null,
};

const THRESHOLDS: RuleThreshold[] = [
  {
    rule_key: "machine.temperature_c",
    display_name: "Spindle temperature",
    unit: "°C",
    warning_threshold: 70,
    critical_threshold: 85,
    comparison: "gte",
    notes: null,
  },
  {
    rule_key: "machine.vibration_mm_s",
    display_name: "Spindle vibration",
    unit: "mm/s",
    warning_threshold: 2.5,
    critical_threshold: 4,
    comparison: "gte",
    notes: null,
  },
];

function event(over: Partial<MaintenanceEvent> = {}): MaintenanceEvent {
  return {
    maintenance_id: 1,
    machine_id: "CNC-03",
    maintenance_date: "2026-09-16",
    duration_hours: 4,
    maintenance_type: "preventive",
    maintenance_status: "scheduled",
    description: "Spindle bearing overhaul",
    ...over,
  };
}

describe("machine type", () => {
  it("names the type the way a factory manager says it", () => {
    expect(machineTypeLabel("CNC_LATHE")).toBe("CNC lathe");
    expect(machineTypeLabel("CNC_MILL")).toBe("CNC milling machine");
  });

  it("falls back to the type itself rather than showing nothing", () => {
    expect(machineTypeLabel("CNC_GRINDER")).toBe("CNC GRINDER");
  });
});

describe("status notes", () => {
  it("says that an idle machine still counts as available", () => {
    // Why five machines are on the strip and three in an A12 calculation:
    // the two missing ones are mills, not idle machines.
    expect(statusNote("idle")).toContain("capacity");
  });

  it("has nothing to add for a status the MES has not defined", () => {
    expect(statusNote("warming_up")).toBeNull();
  });
});

describe("condition rows", () => {
  it("pairs every reading with the limit the factory set", () => {
    const rows = conditionRows(CNC01, THRESHOLDS);
    const temperature = rows[0];

    expect(temperature.label).toBe("Spindle temperature");
    expect(temperature.reading).toBe(72.5);
    expect(temperature.warning).toBe(70);
    expect(temperature.critical).toBe(85);
    expect(temperature.level).toBe("at_limit");
  });

  it("reports a missing reading as unknown, never as zero", () => {
    const vibration = conditionRows(CNC02, THRESHOLDS)[1];

    expect(vibration.reading).toBeNull();
    expect(vibration.level).toBe("unknown");
  });

  it("still lists a reading the factory has set no limit for", () => {
    const rows = conditionRows(CNC01, THRESHOLDS);
    const utilisation = rows[2];

    expect(rows).toHaveLength(3);
    expect(utilisation.reading).toBe(84.2);
    expect(utilisation.warning).toBeNull();
    expect(utilisation.level).toBe("within");
  });
});

describe("maintenance for one machine", () => {
  const maintenance: FactoryMaintenance = {
    thisWeek: {
      events: [
        event({ maintenance_id: 2, maintenance_date: "2026-09-17" }),
        event({ maintenance_id: 1, maintenance_date: "2026-09-16" }),
        event({ maintenance_id: 9, machine_id: "CNC-05", maintenance_date: "2026-09-18" }),
      ],
      hours_by_machine: { "CNC-03": 20 },
      machines_under_maintenance_today: [],
    },
    nextWeek: {
      events: [event({ maintenance_id: 7, machine_id: "CNC-04", maintenance_date: "2026-09-22" })],
      hours_by_machine: { "CNC-04": 3 },
      machines_under_maintenance_today: [],
    },
    window: { label: "this_week", start: "2026-09-15", end: "2026-09-20", days: 6 },
  };

  it("takes only this machine's events, oldest first", () => {
    const service = machineMaintenance("CNC-03", maintenance);

    expect(service.thisWeek.map((e) => e.maintenance_date)).toEqual(["2026-09-16", "2026-09-17"]);
    expect(service.nextWeek).toEqual([]);
  });

  it("uses the tool's own hour total rather than adding the events up", () => {
    // The screen must never produce a factory figure of its own: 20 h is what
    // the capacity engine subtracts, and it is what the panel shows.
    expect(machineMaintenance("CNC-03", maintenance).scheduledHours).toBe(20);
  });

  it("reports zero hours for a machine with nothing booked", () => {
    const service = machineMaintenance("CNC-01", maintenance);

    expect(service.available).toBe(true);
    expect(service.scheduledHours).toBe(0);
    expect(service.thisWeek).toEqual([]);
  });

  it("carries next week's events for a machine with none this week", () => {
    expect(machineMaintenance("CNC-04", maintenance).nextWeek).toHaveLength(1);
  });

  it("marks a machine that is under maintenance today", () => {
    const active: FactoryMaintenance = {
      ...maintenance,
      thisWeek: { ...maintenance.thisWeek!, machines_under_maintenance_today: ["CNC-03"] },
    };

    expect(machineMaintenance("CNC-03", active).activeToday).toBe(true);
    expect(machineMaintenance("CNC-01", active).activeToday).toBe(false);
  });

  it("distinguishes an unreadable schedule from an empty one", () => {
    // An empty list would read as "no maintenance", which is a different
    // claim from "the MES did not answer".
    const service = machineMaintenance("CNC-03", { thisWeek: null, nextWeek: null, window: null });

    expect(service.available).toBe(false);
    expect(service.scheduledHours).toBeNull();
  });

  it("survives having no maintenance data at all", () => {
    expect(machineMaintenance("CNC-03", null).available).toBe(false);
  });
});

describe("maintenance kind", () => {
  it("reads as a sentence, not a database value", () => {
    expect(maintenanceKind("preventive")).toBe("Preventive");
    expect(maintenanceKind("condition_based")).toBe("Condition based");
  });
});
