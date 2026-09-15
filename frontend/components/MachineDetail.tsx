"use client";

import { useEffect, useRef } from "react";

import { formatHours, formatNumber } from "@/lib/format";
import {
  conditionRows,
  machineMaintenance,
  machineTypeLabel,
  maintenanceKind,
  statusNote,
} from "@/lib/machines";
import { formatDay, wallClock, zoneCity } from "@/lib/timezone";
import type {
  FactoryMaintenance,
  MachineStatus,
  MaintenanceEvent,
  RuleThreshold,
} from "@/lib/types";

import { useTime } from "./TimeProvider";
import { Dot, Eyebrow, type Tone } from "./ui";

const STATUS_TONE: Record<string, Tone> = {
  running: "ok",
  idle: "muted",
  maintenance: "warn",
  offline: "bad",
};

/**
 * One machine's MES record, in full.
 *
 * The strip carries the live readings, because a status board that hides its
 * numbers behind a click is not a status board. This panel carries everything
 * a reading cannot say: what the machine is, what it is working on, the limits
 * its readings are judged against, and the maintenance booked against it —
 * which is what makes an answer like "CNC-03 is the bottleneck" legible.
 *
 * A native <dialog> does the modal work: Escape closes it, focus is trapped
 * and restored, and the page behind it is inert. The left and right arrow keys
 * move between machines, so five machines can be compared without closing it.
 */
export function MachineDetail({
  machine,
  machines,
  thresholds,
  maintenance,
  onClose,
  onSelect,
}: {
  machine: MachineStatus;
  machines: MachineStatus[];
  thresholds: RuleThreshold[];
  maintenance: FactoryMaintenance | null;
  onClose: () => void;
  onSelect: (machineId: string) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const { factoryZone } = useTime();

  useEffect(() => {
    const element = dialog.current;
    if (element && !element.open) element.showModal();
  }, []);

  const index = machines.findIndex((m) => m.machine_id === machine.machine_id);
  const previous = index > 0 ? machines[index - 1] : null;
  const next = index >= 0 && index < machines.length - 1 ? machines[index + 1] : null;

  const rows = conditionRows(machine, thresholds);
  const service = machineMaintenance(machine.machine_id, maintenance);
  const reading = machine.last_reading_at && factoryZone
    ? wallClock(new Date(machine.last_reading_at), factoryZone)
    : null;

  return (
    <dialog
      ref={dialog}
      onClose={onClose}
      onCancel={onClose}
      onClick={(event) => {
        // The backdrop is the dialog itself; its children are the panel.
        if (event.target === dialog.current) dialog.current?.close();
      }}
      onKeyDown={(event) => {
        if (event.key === "ArrowLeft" && previous) onSelect(previous.machine_id);
        if (event.key === "ArrowRight" && next) onSelect(next.machine_id);
      }}
      aria-label={`${machine.machine_id} details`}
      className="m-auto w-[min(92vw,600px)] rounded-2xl border border-line-strong bg-raised p-0
                 text-fg shadow-2xl backdrop:bg-black/50 backdrop:backdrop-blur-[2px]"
    >
      <div className="max-h-[85vh] overflow-y-auto px-5 py-5 sm:px-6">
        <header className="flex items-start justify-between gap-4">
          <div>
            <h2 className="font-mono text-[17px] font-medium tracking-tight">{machine.machine_id}</h2>
            <p className="mt-0.5 text-[13px] text-fg-2">{machine.machine_name}</p>
          </div>
          <div className="flex items-center gap-3">
            <span className="inline-flex items-center gap-1.5 text-[12px] text-fg-2">
              <Dot tone={STATUS_TONE[machine.status] ?? "muted"} pulse={machine.status === "running"} />
              {machine.status}
            </span>
            <button
              type="button"
              onClick={() => dialog.current?.close()}
              aria-label="Close"
              className="-mr-1 -mt-1 rounded-lg p-1.5 text-fg-3 transition-colors hover:bg-tint/[0.06] hover:text-fg"
            >
              <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
                <path d="M4 4l8 8M12 4l-8 8" strokeLinecap="round" />
              </svg>
            </button>
          </div>
        </header>

        {statusNote(machine.status) && (
          <p className="mt-3 rounded-lg border border-line bg-tint/[0.02] px-3 py-2 text-[12.5px] text-fg-2">
            {statusNote(machine.status)}
          </p>
        )}

        {/* ------------------------------------------------- what it is */}
        <section className="mt-5">
          <Eyebrow>Machine</Eyebrow>
          <dl className="mt-2.5 grid grid-cols-1 gap-x-6 gap-y-2.5 sm:grid-cols-2">
            <Fact label="Type" value={machineTypeLabel(machine.machine_type)} mono={false}>
              <span className="font-mono text-[11px] text-fg-3">{machine.machine_type}</span>
            </Fact>
            <Fact label="Current job" value={machine.current_job ?? "none loaded"} />
            {/*
              A display column (ADR-7): the capacity engine reads the shift
              calendar, never this. Labelled for what it is so a figure here
              and a figure in an answer can never look like a contradiction.
            */}
            <Fact
              label="Hours left this week"
              value={
                machine.available_hours === null ? "not recorded" : formatHours(machine.available_hours)
              }
            >
              <span className="text-[11px] text-fg-3">MES display field</span>
            </Fact>
            <Fact
              label="Reading taken"
              value={
                reading
                  ? `${reading.time} · ${formatDay(reading.date)}`
                  : machine.last_reading_at ?? "not recorded"
              }
            >
              {reading && factoryZone && (
                <span className="text-[11px] text-fg-3">factory time in {zoneCity(factoryZone)}</span>
              )}
            </Fact>
          </dl>
        </section>

        {/* ------------------------------------------------- limits */}
        <section className="mt-5 border-t border-line pt-4">
          <div className="flex items-baseline justify-between gap-4">
            <Eyebrow>Condition limits</Eyebrow>
            <span className="text-[11px] text-fg-3">set by the factory</span>
          </div>
          <ul className="mt-2.5 divide-y divide-line">
            {rows.map((row) => (
              <li key={row.key} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2">
                <div>
                  <p className="text-[13px] text-fg">{row.label}</p>
                  <p className="text-[11.5px] text-fg-3">
                    {row.warning === null
                      ? "no limit set"
                      : `warn at ${formatNumber(row.warning)}${row.unit ? ` ${row.unit}` : ""}`}
                    {row.critical !== null &&
                      ` · critical at ${formatNumber(row.critical)}${row.unit ? ` ${row.unit}` : ""}`}
                  </p>
                </div>
                <p
                  className={`font-mono text-[13px] tabular ${
                    row.level === "at_limit" ? "text-warn" : row.level === "unknown" ? "text-fg-3" : "text-fg"
                  }`}
                >
                  {row.reading === null ? "no reading" : `${formatNumber(row.reading)} ${row.unit}`}
                  {row.level === "at_limit" && (
                    <span className="ml-2 text-[11px] uppercase tracking-[0.08em]">at limit</span>
                  )}
                </p>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[11.5px] leading-relaxed text-fg-3">
            A reading at its limit is marked, not judged. Whether this machine may keep running is
            answered by the rule engine — ask about it to see the check.
          </p>
        </section>

        {/* ------------------------------------------------- maintenance */}
        <section className="mt-5 border-t border-line pt-4">
          <div className="flex items-baseline justify-between gap-4">
            <Eyebrow>Maintenance</Eyebrow>
            {service.available && (
              <span className="text-[11px] text-fg-3">
                {service.activeToday ? "active today" : "nothing active today"}
              </span>
            )}
          </div>

          {!service.available ? (
            <p className="mt-2.5 text-[13px] text-fg-3">
              The maintenance schedule could not be read from the MES.
            </p>
          ) : (
            <>
              <p className="mt-2.5 text-[13px] text-fg-2">
                {service.scheduledHours
                  ? `${formatHours(service.scheduledHours)} scheduled in the rest of this week, taken off this machine's available hours.`
                  : "Nothing scheduled in the rest of this week."}
              </p>
              <Events events={service.thisWeek} />
              {service.nextWeek.length > 0 && (
                <>
                  <p className="mt-3 text-[11.5px] uppercase tracking-[0.08em] text-fg-3">Next week</p>
                  <Events events={service.nextWeek} />
                </>
              )}
            </>
          )}
        </section>

        {/* ------------------------------------------------- navigation */}
        <footer className="mt-5 flex items-center justify-between gap-3 border-t border-line pt-4">
          <p className="text-[11.5px] text-fg-3">
            From <span className="font-mono">machines</span> and{" "}
            <span className="font-mono">maintenance</span>, read-only.
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={!previous}
              onClick={() => previous && onSelect(previous.machine_id)}
              className="chip font-mono text-[12px]"
            >
              ← {previous?.machine_id ?? "—"}
            </button>
            <button
              type="button"
              disabled={!next}
              onClick={() => next && onSelect(next.machine_id)}
              className="chip font-mono text-[12px]"
            >
              {next?.machine_id ?? "—"} →
            </button>
          </div>
        </footer>
      </div>
    </dialog>
  );
}

function Fact({
  label,
  value,
  mono = true,
  children,
}: {
  label: string;
  value: string;
  mono?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <div>
      <dt className="text-[11px] uppercase tracking-[0.1em] text-fg-3">{label}</dt>
      <dd className={`mt-0.5 text-[13px] text-fg ${mono ? "font-mono" : ""}`}>
        {value}
        {children && <span className="ml-2">{children}</span>}
      </dd>
    </div>
  );
}

function Events({ events }: { events: MaintenanceEvent[] }) {
  if (events.length === 0) return null;

  return (
    <ul className="mt-2 divide-y divide-line">
      {events.map((event) => (
        <li key={event.maintenance_id} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 py-1.5">
          <span className="font-mono text-[12.5px] text-fg">{formatDay(event.maintenance_date)}</span>
          <span className="font-mono text-[12.5px] tabular text-fg-2">{formatHours(event.duration_hours)}</span>
          <span className="text-[12.5px] text-fg-2">{maintenanceKind(event.maintenance_type)}</span>
          <span className="text-[11px] uppercase tracking-[0.08em] text-fg-3">{event.maintenance_status}</span>
          {event.description && (
            <span className="basis-full text-[12px] text-fg-3">{event.description}</span>
          )}
        </li>
      ))}
    </ul>
  );
}
