import { formatHours, formatNumber, formatReading, LEVEL_TONE } from "@/lib/format";
import type { AgentRun, ThresholdCheck } from "@/lib/types";

/**
 * The engine's own working, shown rather than summarised.
 *
 * A capacity figure a manager cannot check is a figure a manager has to trust.
 * `CapacityResult.formula` is built by the calculation engine line by line as
 * it works, so what is printed here is the arithmetic that produced the number
 * — not a re-derivation, and not a description of one.
 */
export function CalculationPanel({ run }: { run: AgentRun }) {
  const capacity = run.capacity;
  if (!capacity) return null;

  return (
    <section className="card" aria-labelledby="working">
      <h2 id="working" className="card-title flex items-center justify-between">
        <span>How the number was calculated</span>
        <span className="font-normal normal-case tracking-normal text-slate-400">
          deterministic Python · no language model
        </span>
      </h2>

      <div className="p-4">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="text-left text-slate-500">
              <th className="pb-2 font-medium">Machine</th>
              <th className="pb-2 text-right font-medium">Planned</th>
              <th className="pb-2 text-right font-medium">Maintenance</th>
              <th className="pb-2 text-right font-medium">Effective</th>
              <th className="pb-2 text-right font-medium">Parts</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200/70">
            {capacity.machines.map((line) => (
              <tr
                key={line.machine_id}
                className={line.eligible ? "" : "text-slate-400"}
                title={line.ineligible_reason ?? undefined}
              >
                <td className="py-1.5">
                  <span className="mono font-medium">{line.machine_id}</span>
                  {!line.eligible && <span className="ml-2 text-[11px]">not eligible</span>}
                </td>
                <td className="py-1.5 text-right tabular">{formatHours(line.planned_hours)}</td>
                <td className="py-1.5 text-right tabular">
                  {line.maintenance_hours > 0 ? (
                    <span className="text-amber-700">−{formatHours(line.maintenance_hours)}</span>
                  ) : (
                    <span className="text-slate-300">—</span>
                  )}
                </td>
                <td className="py-1.5 text-right tabular font-medium">
                  {formatHours(line.effective_hours)}
                </td>
                <td className="py-1.5 text-right tabular">{formatNumber(line.parts_possible)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <pre className="mono mt-3 overflow-x-auto whitespace-pre-wrap rounded-md bg-slate-900 p-3 leading-relaxed text-slate-200">
          {capacity.formula.join("\n")}
        </pre>

        <p className="mt-2 text-[12px] text-slate-500">
          Cycle time {formatNumber(capacity.cycle_time_min)} min/part on{" "}
          <span className="mono">{capacity.required_machine_type}</span>
          {capacity.material_id && (
            <>
              {" "}
              · material <span className="mono">{capacity.material_id}</span>
              {capacity.available_quantity !== null &&
                ` · ${formatNumber(capacity.available_quantity)} on hand`}
            </>
          )}
          {" · "}
          {capacity.binding_constraint === "material"
            ? "material is the binding constraint"
            : "machine hours are the binding constraint"}
        </p>
      </div>
    </section>
  );
}

/**
 * Condition checks, each naming the limit it was compared against.
 *
 * S2 and S5 both require this: a verdict without its threshold is an opinion.
 * A machine whose sensor cannot be read is shown as *not assessable* — never
 * as healthy, which is the distinction the seeded CNC-02 exists to prove.
 */
export function HealthPanel({ run }: { run: AgentRun }) {
  if (run.health.length === 0) return null;

  return (
    <section className="card" aria-labelledby="health">
      <h2 id="health" className="card-title flex items-center justify-between">
        <span>Condition checks</span>
        <span className="font-normal normal-case tracking-normal text-slate-400">
          rule-based · not predictive maintenance
        </span>
      </h2>

      <ul className="divide-y divide-slate-200/70">
        {run.health.map((machine) => (
          <li key={machine.machine_id} className="px-4 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="mono font-semibold text-slate-900">{machine.machine_id}</span>
              <span
                className={`pill ${
                  machine.can_produce
                    ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20"
                    : "bg-amber-50 text-amber-800 ring-amber-600/25"
                }`}
              >
                {machine.can_produce ? "can continue production" : "cannot continue production"}
              </span>
              {!machine.fully_assessable && (
                <span className="pill bg-slate-100 text-slate-600 ring-slate-500/20">
                  not fully assessable
                </span>
              )}
            </div>

            <ul className="mt-2 space-y-1">
              {machine.checks.map((check) => (
                <Check key={check.rule_key} check={check} />
              ))}
            </ul>

            {machine.attention_note && (
              <p className="mt-1.5 text-[12px] text-amber-700">{machine.attention_note}</p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function Check({ check }: { check: ThresholdCheck }) {
  return (
    <li className="flex flex-wrap items-baseline gap-x-2 text-[12px]">
      <span className={`pill ${LEVEL_TONE[check.level]}`}>{check.level.replace("_", " ")}</span>
      <span className="text-slate-600">{check.display_name}</span>
      <span className="tabular font-medium text-slate-900">
        {formatReading(check.reading, check.unit)}
      </span>
      {check.warning_threshold !== null && (
        <span className="tabular text-slate-400">
          limit {formatNumber(check.warning_threshold)} {check.unit}
        </span>
      )}
    </li>
  );
}

/**
 * Plan versus actual, with the causes ranked by how many parts each cost.
 *
 * The ranking is the engine's: hours of downtime and counts of rejects are not
 * comparable until the cycle time converts both into parts. The panel prints
 * the order it was given.
 */
export function AnalysisPanel({ run }: { run: AgentRun }) {
  const analysis = run.analysis;
  if (!analysis) return null;

  return (
    <section className="card" aria-labelledby="analysis">
      <h2 id="analysis" className="card-title">
        Plan versus actual
      </h2>

      <div className="p-4">
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Figure label="Planned" value={formatNumber(analysis.planned_quantity)} />
          <Figure label="Produced" value={formatNumber(analysis.produced_quantity)} />
          <Figure label="Rejected" value={formatNumber(analysis.rejected_quantity)} />
          <Figure label="Downtime" value={formatHours(analysis.downtime_hours)} />
        </dl>

        {analysis.factors.length > 0 && (
          <ol className="mt-4 space-y-2">
            {analysis.factors.map((factor, index) => (
              <li key={`${factor.kind}-${factor.label}`} className="flex gap-3 text-[13px]">
                <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-slate-100 text-[11px] font-semibold text-slate-600 tabular">
                  {index + 1}
                </span>
                <div className="min-w-0">
                  <p className="text-slate-800">
                    {factor.label}
                    <span className="ml-2 tabular text-slate-500">
                      {factor.impact_parts > 0 ? "−" : "+"}
                      {formatNumber(Math.abs(factor.impact_parts))} parts
                    </span>
                  </p>
                  <p className="text-[12px] text-slate-500">{factor.detail}</p>
                </div>
              </li>
            ))}
          </ol>
        )}

        {analysis.by_machine.length > 0 && (
          <table className="mt-4 w-full text-[12px]">
            <thead>
              <tr className="text-left text-slate-500">
                <th className="pb-2 font-medium">Machine</th>
                <th className="pb-2 text-right font-medium">Planned</th>
                <th className="pb-2 text-right font-medium">Produced</th>
                <th className="pb-2 text-right font-medium">Delta</th>
                <th className="pb-2 text-left font-medium">Downtime</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200/70">
              {analysis.by_machine.map((row) => (
                <tr key={row.machine_id}>
                  <td className="py-1.5 mono font-medium">{row.machine_id}</td>
                  <td className="py-1.5 text-right tabular">{formatNumber(row.planned_quantity)}</td>
                  <td className="py-1.5 text-right tabular">
                    {formatNumber(row.produced_quantity)}
                  </td>
                  <td
                    className={`py-1.5 text-right tabular font-medium ${
                      row.delta < 0 ? "text-red-600" : "text-emerald-700"
                    }`}
                  >
                    {row.delta > 0 ? "+" : ""}
                    {formatNumber(row.delta)}
                  </td>
                  <td className="py-1.5 text-slate-600">
                    {row.downtime_hours > 0
                      ? `${formatHours(row.downtime_hours)}${
                          row.downtime_reason ? ` — ${row.downtime_reason}` : ""
                        }`
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[11px] font-medium uppercase tracking-[0.06em] text-slate-500">
        {label}
      </dt>
      <dd className="mt-0.5 text-[18px] font-semibold text-slate-900 tabular">{value}</dd>
    </div>
  );
}
