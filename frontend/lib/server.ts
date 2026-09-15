import type {
  FactoryMaintenance,
  Health,
  MachineStatus,
  MachineStatusEnvelope,
  MaintenanceScheduleEnvelope,
  RuleThreshold,
} from "./types";

/**
 * Server-side reads for the first paint.
 *
 * The factory status strip and the header are rendered on the server so the
 * page arrives with real machine state rather than five grey placeholders that
 * fill in a moment later. A backend that is down must still produce a usable
 * page saying so — the question box is useless then, and the screen should be
 * honest about why rather than silently offering it.
 */

const API = process.env.MES_API_URL ?? "http://localhost:8000";

async function read<T>(path: string, timeoutMs = 5000): Promise<T | null> {
  try {
    const response = await fetch(`${API}${path}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
      headers: { accept: "application/json" },
    });
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

async function call<T>(path: string, body: unknown, timeoutMs = 5000): Promise<T | null> {
  try {
    const response = await fetch(`${API}${path}`, {
      method: "POST",
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
      headers: { accept: "application/json", "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

export function getHealth(): Promise<Health | null> {
  return read<Health>("/api/health");
}

export async function getFactory(): Promise<{
  machines: MachineStatus[];
  thresholds: RuleThreshold[];
}> {
  const envelope = await read<MachineStatusEnvelope>("/api/machines");
  return {
    machines: envelope?.data.machines ?? [],
    thresholds: envelope?.data.thresholds ?? [],
  };
}

/**
 * The maintenance behind each machine's detail view.
 *
 * Read here, on the server, through the same controlled tool the agent calls —
 * the browser's proxy exposes no tool route, and widening it for a panel would
 * trade the point of the tool layer for a convenience. Two named windows are
 * requested instead of a date range, so the factory's calendar stays the thing
 * that decides which days "this week" means.
 */
export async function getMaintenance(): Promise<FactoryMaintenance> {
  const [thisWeek, nextWeek] = await Promise.all([
    call<MaintenanceScheduleEnvelope>("/api/tools/get_maintenance_schedule", {
      time_window: "this_week",
    }),
    call<MaintenanceScheduleEnvelope>("/api/tools/get_maintenance_schedule", {
      time_window: "next_week",
    }),
  ]);

  return {
    thisWeek: thisWeek?.data ?? null,
    nextWeek: nextWeek?.data ?? null,
    window: thisWeek?.window ?? null,
  };
}
