import { formatHours, formatNumber, formatReading, humanise } from "@/lib/format";
import type { AgentRun, ThresholdLevel } from "@/lib/types";

import { Dot, Section, type Tone } from "./ui";

/**
 * The engine's working, printed rather than paraphrased.
 *
 * `CapacityResult.formula` is written by the calculation engine as it works,
 * so the lines below are the arithmetic that produced the headline — not a
 * re-derivation of it. The final line is emphasised; nothing is recalculated.
 */
export function Calculation({ run }: { run: AgentRun }) {
  const capacity = run.capacity;
  if (!capacity) return null;

  const [lastLine, ...rest] = [...capacity.formula].reverse();
  const earlier = rest.reverse();

  return (
    <Section title="How the number was calculated" aside="Deterministic · no language model">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[440px] text-[13px]">
          <thead>
            <tr className="text-left">
              {["Machine", "Planned", "Maintenance", "Effective", "Parts"].map((h, i) => (
                <th key={h} className={`eyebrow pb-2.5 font-normal ${i ? "text-right" : ""}`}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="font-mono tabular">
            {capacity.machines.map((line) => {
              const limiting = run.bottleneck?.machine_id === line.machine_id;
              return (
                <tr
                  key={line.machine_id}
                  className={`border-t border-line ${line.eligible ? "" : "text-fg-3"}`}
                  title={line.ineligible_reason ?? undefined}
                >
                  <td className="py-2.5">
                    <span className={limiting ? "text-accent" : "text-fg"}>{line.machine_id}</span>
                    {!line.eligible && <span className="ml-2 font-sans text-[11px]">not eligible</span>}
                  </td>
                  <td className="py-2.5 text-right text-fg-2">{formatHours(line.planned_hours)}</td>
                  <td className="py-2.5 text-right">
                    {line.maintenance_hours > 0 ? (
                      <span className="text-warn">−{formatHours(line.maintenance_hours)}</span>
                    ) : (
                      <span className="text-fg-3">—</span>
                    )}
                  </td>
                  <td className="py-2.5 text-right text-fg">{formatHours(line.effective_hours)}</td>
                  <td className="py-2.5 text-right text-fg">{formatNumber(line.parts_possible)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <pre className="mt-5 overflow-x-auto rounded-xl border border-line bg-canvas/70 p-4 font-mono text-[12px] leading-[1.75] text-fg-3">
        {earlier.map((line) => (
          <span key={line} className="block">
            {line}
          </span>
        ))}
        {lastLine && (
          <span className="mt-1 block border-t border-line pt-2 text-fg">
            <span className="mr-2 text-accent">▸</span>
            {lastLine}
          </span>
        )}
      </pre>
    </Section>
  );
}

const LEVEL: Record<ThresholdLevel, { tone: Tone; label: string }> = {
  normal: { tone: "ok", label: "Normal" },
  warning: { tone: "warn", label: "Warning" },
  critical: { tone: "bad", label: "Critical" },
  not_assessable: { tone: "muted", label: "No reading" },
};

/**
 * Condition checks, each naming the limit it was compared against — a verdict
 * without its threshold is an opinion. A machine whose sensor is silent is
 * "not fully assessable", never healthy.
 */
export function Health({ run }: { run: AgentRun }) {
  if (run.health.length === 0) return null;

  return (
    <Section title="Condition checks" aside="Rule-based · not predictive maintenance">
      <ul className="space-y-3">
        {run.health.map((machine, index) => (
          <li
            key={machine.machine_id}
            className={`rounded-xl border px-4 py-3.5 ${
              index === 0 && run.health.length > 1 && machine.breaches > 0
                ? "border-accent/30 bg-accent-soft"
                : "border-line bg-white/[0.015]"
            }`}
          >
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="font-mono text-[14px] font-medium text-fg">{machine.machine_id}</span>
              <span className={`text-[13px] ${machine.can_produce ? "text-ok" : "text-warn"}`}>
                {machine.can_produce ? "Can continue production" : "Cannot continue production"}
              </span>
              {!machine.fully_assessable && (
                <span className="text-[12px] text-fg-3">· not fully assessable</span>
              )}
            </div>

            <ul className="mt-2.5 grid gap-x-10 gap-y-1.5 sm:grid-cols-2">
              {machine.checks.map((check) => {
                const level = LEVEL[check.level];
                return (
                  <li key={check.rule_key} className="flex items-center gap-2 text-[13px]">
                    <Dot tone={level.tone} />
                    <span className="text-fg-2">{check.display_name}</span>
                    <span className="ml-auto font-mono text-fg tabular">
                      {formatReading(check.reading, check.unit)}
                    </span>
                    {check.warning_threshold !== null && (
                      <span className="font-mono text-[11px] text-fg-3 tabular">
                        / {formatNumber(check.warning_threshold)}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>

            {machine.attention_note && (
              <p className="mt-2.5 text-[13px] leading-relaxed text-fg-2">{machine.attention_note}</p>
            )}
          </li>
        ))}
      </ul>
    </Section>
  );
}

/**
 * Plan versus actual, with causes in the order the engine ranked them — by
 * parts lost, once the cycle time has made hours and rejects comparable.
 */
export function Analysis({ run }: { run: AgentRun }) {
  const a = run.analysis;
  if (!a) return null;

  return (
    <Section title="Plan versus actual" aside={a.part_id ?? undefined}>
      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-4">
        {[
          ["Planned", formatNumber(a.planned_quantity)],
          ["Produced", formatNumber(a.produced_quantity)],
          ["Rejected", formatNumber(a.rejected_quantity)],
          ["Downtime", formatHours(a.downtime_hours)],
        ].map(([label, value]) => (
          <div key={label} className="bg-surface px-4 py-3">
            <dt className="eyebrow">{label}</dt>
            <dd className="mt-1 text-[22px] font-semibold tracking-tight text-fg tabular">{value}</dd>
          </div>
        ))}
      </dl>

      {a.factors.length > 0 && (
        <ol className="mt-5 space-y-3">
          {a.factors.map((factor, index) => (
            <li key={`${factor.kind}-${factor.label}`} className="flex gap-4">
              <span className="w-5 shrink-0 pt-0.5 font-mono text-[12px] text-accent tabular">
                {String(index + 1).padStart(2, "0")}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-3">
                  <p className="text-[14px] text-fg">{factor.label}</p>
                  <span
                    className={`shrink-0 font-mono text-[13px] tabular ${
                      factor.impact_parts > 0 ? "text-warn" : "text-ok"
                    }`}
                  >
                    {factor.impact_parts > 0 ? "−" : "+"}
                    {formatNumber(Math.abs(factor.impact_parts))} parts
                  </span>
                </div>
                <p className="mt-0.5 text-[13px] leading-relaxed text-fg-3">{factor.detail}</p>
              </div>
            </li>
          ))}
        </ol>
      )}

      {a.by_machine.length > 0 && (
        <div className="mt-5 overflow-x-auto">
          <table className="w-full min-w-[440px] text-[13px]">
            <thead>
              <tr className="text-left">
                {["Machine", "Planned", "Produced", "Delta", "Downtime"].map((h, i) => (
                  <th key={h} className={`eyebrow pb-2.5 font-normal ${i && i < 4 ? "text-right" : ""} ${i === 4 ? "pl-6" : ""}`}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="font-mono tabular">
              {a.by_machine.map((row) => (
                <tr key={row.machine_id} className="border-t border-line">
                  <td className="py-2.5 text-fg">{row.machine_id}</td>
                  <td className="py-2.5 text-right text-fg-2">{formatNumber(row.planned_quantity)}</td>
                  <td className="py-2.5 text-right text-fg">{formatNumber(row.produced_quantity)}</td>
                  <td className={`py-2.5 text-right ${row.delta < 0 ? "text-warn" : "text-ok"}`}>
                    {row.delta > 0 ? "+" : ""}
                    {formatNumber(row.delta)}
                  </td>
                  <td className="py-2.5 pl-6 font-sans text-fg-2">
                    {row.downtime_hours > 0
                      ? `${formatHours(row.downtime_hours)} · ${row.downtime_reason ?? humanise("unplanned")}`
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}
