"use client";

import { useState } from "react";

import { formatNumber, readingLevel } from "@/lib/format";
import type { FactoryMaintenance, MachineStatus, RuleThreshold } from "@/lib/types";

import { MachineDetail } from "./MachineDetail";
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
 *
 * Every card opens the machine's full record. The readings stay here rather
 * than moving into that panel: the strip is the status board, and a number a
 * manager has to click to see is a number they will not see.
 */
export function MachineStrip({
  machines,
  thresholds,
  maintenance = null,
}: {
  machines: MachineStatus[];
  thresholds: RuleThreshold[];
  maintenance?: FactoryMaintenance | null;
}) {
  const [selected, setSelected] = useState<string | null>(null);

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

  const open = machines.find((m) => m.machine_id === selected) ?? null;

  return (
    <>
      <ul className="panel flex snap-x divide-x divide-line overflow-x-auto [scrollbar-width:none] lg:grid lg:grid-cols-5 lg:overflow-hidden">
        {machines.map((m) => (
          <li
            key={m.machine_id}
            className="group relative min-w-[210px] shrink-0 snap-start px-4 py-3.5 transition-colors hover:bg-tint/[0.025] focus-within:bg-tint/[0.025] lg:min-w-0"
          >
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

            <p className="mt-2.5 text-[11px] text-fg-3 transition-colors group-hover:text-accent group-focus-within:text-accent">
              Details
              <span aria-hidden className="ml-1">
                →
              </span>
            </p>

            {/*
              The whole card is the target, but a <button> may not contain a
              description list, so the control sits over the card instead of
              wrapping it. It keeps the card's markup valid and still gives a
              screen reader one named control per machine.
            */}
            <button
              type="button"
              onClick={() => setSelected(m.machine_id)}
              aria-haspopup="dialog"
              aria-label={`${m.machine_id} details`}
              className="absolute inset-0 cursor-pointer rounded-lg focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent"
            />
          </li>
        ))}
      </ul>

      {open && (
        <MachineDetail
          key={open.machine_id}
          machine={open}
          machines={machines}
          thresholds={thresholds}
          maintenance={maintenance}
          onClose={() => setSelected(null)}
          onSelect={setSelected}
        />
      )}
    </>
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
