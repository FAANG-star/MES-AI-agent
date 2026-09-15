/**
 * What the machine detail view knows, derived without arithmetic.
 *
 * The strip shows readings; this file turns the rest of a machine's MES record
 * into rows a factory manager can read. The same rule as everywhere else in
 * the interface applies: nothing here computes a factory figure. Limits come
 * from `rule_thresholds`, scheduled hours come from the maintenance tool's own
 * total, and a reading's standing against its limit is `readingLevel` — a
 * colour, not a verdict. Whether a machine may keep running is decided by the
 * rule engine inside an answer, with the limit cited.
 *
 * Kept out of the component so it can be tested without a browser.
 */

import { readingLevel, type ReadingLevel } from "./format";
import type { FactoryMaintenance, MachineStatus, MaintenanceEvent, RuleThreshold } from "./types";

const MACHINE_TYPES: Record<string, string> = {
  CNC_LATHE: "CNC lathe",
  CNC_MILL: "CNC milling machine",
};

/** "CNC_LATHE" → "CNC lathe". An unmapped type reads as itself, never blank. */
export function machineTypeLabel(type: string): string {
  return MACHINE_TYPES[type] ?? type.replaceAll("_", " ");
}

/**
 * What a status means for capacity.
 *
 * Idle is the one worth spelling out: an idle machine is counted as available,
 * which is why a factory manager sees five machines on the strip and three in
 * an A12 calculation — the missing two are the wrong machine type, not idle.
 */
const STATUS_NOTES: Record<string, string> = {
  running: "Producing now. Counted as available.",
  idle: "No job loaded. Still counted as available — idle hours are capacity.",
  maintenance: "Under maintenance. Its hours are not counted as available.",
  offline: "Not available. Excluded from capacity.",
};

export function statusNote(status: string): string | null {
  return STATUS_NOTES[status] ?? null;
}

export interface ConditionRow {
  key: string;
  label: string;
  reading: number | null;
  unit: string;
  warning: number | null;
  critical: number | null;
  level: ReadingLevel;
  notes: string | null;
}

const CONDITION_KEYS: { rule: string; label: string; of: (m: MachineStatus) => number | null }[] = [
  { rule: "machine.temperature_c", label: "Temperature", of: (m) => m.temperature_c },
  { rule: "machine.vibration_mm_s", label: "Vibration", of: (m) => m.vibration_mm_s },
  { rule: "machine.utilization_pct", label: "Utilisation", of: (m) => m.utilization_pct },
];

/**
 * Each reading beside the limit the factory set for it.
 *
 * A reading with no threshold row is still listed: the value is real even when
 * the factory has set no limit for it, and hiding it would be a silent edit.
 */
export function conditionRows(
  machine: MachineStatus,
  thresholds: RuleThreshold[],
): ConditionRow[] {
  return CONDITION_KEYS.map(({ rule, label, of }) => {
    const threshold = thresholds.find((t) => t.rule_key === rule) ?? null;
    const reading = of(machine);
    return {
      key: rule,
      label: threshold?.display_name || label,
      reading,
      unit: threshold?.unit ?? "",
      warning: threshold?.warning_threshold ?? null,
      critical: threshold?.critical_threshold ?? null,
      level: readingLevel(reading, threshold?.warning_threshold ?? null),
      notes: threshold?.notes ?? null,
    };
  });
}

export interface MachineMaintenance {
  /** False when the schedule could not be read — different from "nothing scheduled". */
  available: boolean;
  activeToday: boolean;
  /** The tool's own total for this machine in the current window. */
  scheduledHours: number | null;
  thisWeek: MaintenanceEvent[];
  nextWeek: MaintenanceEvent[];
}

function forMachine(events: MaintenanceEvent[], machineId: string): MaintenanceEvent[] {
  return events
    .filter((e) => e.machine_id === machineId)
    .slice()
    .sort((a, b) => a.maintenance_date.localeCompare(b.maintenance_date));
}

export function machineMaintenance(
  machineId: string,
  maintenance: FactoryMaintenance | null,
): MachineMaintenance {
  const thisWeek = maintenance?.thisWeek ?? null;
  const nextWeek = maintenance?.nextWeek ?? null;

  return {
    available: thisWeek !== null,
    activeToday: (thisWeek?.machines_under_maintenance_today ?? []).includes(machineId),
    scheduledHours: thisWeek ? (thisWeek.hours_by_machine[machineId] ?? 0) : null,
    thisWeek: forMachine(thisWeek?.events ?? [], machineId),
    nextWeek: forMachine(nextWeek?.events ?? [], machineId),
  };
}

/** "preventive" → "Preventive". Presentation only. */
export function maintenanceKind(type: string): string {
  const words = type.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
