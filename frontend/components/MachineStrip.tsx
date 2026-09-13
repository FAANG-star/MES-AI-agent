import { formatNumber, readingLevel } from "@/lib/format";
import type { MachineStatus, RuleThreshold } from "@/lib/types";

import { Dot, type Tone } from "./ui";

const STATUS_TONE: Record<string, Tone> = {
  running: "ok",
  idle: "muted",
  maintenance: "warn",
  offline: "bad",
};

/**
 * The five machines as the MES reports them right now.
 *
 * Readings, not verdicts. A value at its limit is marked so the eye finds it,
 * but whether a machine may keep running is decided by the rule engine inside
 * an answer. A sensor that sends nothing reads "—", never zero.
 */
export function MachineStrip({
  machines,
  thresholds,
}: {
  machines: MachineStatus[];
  thresholds: RuleThreshold[];
}) {
  const limit = (key: string) =>
    thresholds.find((t) => t.rule_key === key)?.warning_threshold ?? null;
  const tempLimit = limit("machine.temperature_c");
  const vibLimit = limit("machine.vibration_mm_s");

  if (machines.length === 0) {
    return (
      <div className="panel px-5 py-4 text-[13px] text-fg-3">
        No machine data — the MES backend is not answering.
      </div>
    );
  }

  return (
    <ul className="panel flex snap-x divide-x divide-line overflow-x-auto [scrollbar-width:none] lg:grid lg:grid-cols-5 lg:overflow-hidden">
      {machines.map((m) => (
        <li key={m.machine_id} className="min-w-[210px] shrink-0 snap-start px-4 py-3.5 lg:min-w-0">
          <div className="flex items-center justify-between gap-2">
            <span className="font-mono text-[13px] font-medium text-fg">{m.machine_id}</span>
            <span className="inline-flex items-center gap-1.5 text-[11px] text-fg-2">
              <Dot tone={STATUS_TONE[m.status] ?? "muted"} pulse={m.status === "running"} />
              {m.status}
            </span>
          </div>

          <dl className="mt-3 grid grid-cols-3 gap-2">
            <Reading label="Temp" value={m.temperature_c} unit="°C" limit={tempLimit} />
            <Reading label="Vib" value={m.vibration_mm_s} unit="mm/s" limit={vibLimit} />
            <Reading label="Util" value={m.utilization_pct} unit="%" limit={null} />
          </dl>
        </li>
      ))}
    </ul>
  );
}

function Reading({
  label,
  value,
  unit,
  limit,
}: {
  label: string;
  value: number | null;
  unit: string;
  limit: number | null;
}) {
  const level = readingLevel(value, limit);

  return (
    <div
      title={
        level === "unknown"
          ? "No reading — the sensor is offline, not zero."
          : level === "at_limit" && limit !== null
            ? `At or past the ${formatNumber(limit)} ${unit} limit`
            : undefined
      }
    >
      <dt className="text-[10px] uppercase tracking-[0.1em] text-fg-3">{label}</dt>
      <dd
        className={`mt-0.5 font-mono text-[13px] tabular ${
          level === "at_limit" ? "text-warn" : level === "unknown" ? "text-fg-3" : "text-fg"
        }`}
      >
        {value === null ? "—" : formatNumber(value)}
        <span className="ml-0.5 text-[10px] text-fg-3">{value === null ? "" : unit}</span>
      </dd>
    </div>
  );
}
