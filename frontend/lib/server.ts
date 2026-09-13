import type { Health, MachineStatus, MachineStatusEnvelope, RuleThreshold } from "./types";

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
