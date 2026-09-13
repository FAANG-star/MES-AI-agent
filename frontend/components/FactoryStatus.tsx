import { formatNumber, machineTone, readingTone } from "@/lib/format";
import type { MachineStatus, RuleThreshold } from "@/lib/types";

/**
 * The five machines, as the MES currently reports them.
 *
 * This strip is deliberately *not* a verdict. A reading past its limit is
 * coloured red so the eye can find it, but whether a machine may keep running
 * is a rule-engine decision that belongs to an answer, with its thresholds
 * cited. The strip shows readings; the copilot draws conclusions.
 *
 * A missing reading reads "—", never 0. CNC-02's vibration sensor is offline
 * in the seeded factory, and silence from a sensor is not a passing grade.
 */
export function FactoryStatus({
  machines,
  thresholds,
}: {
  machines: MachineStatus[];
  thresholds: RuleThreshold[];
}) {
  const limit = (key: string) =>
    thresholds.find((t) => t.rule_key === key)?.warning_threshold ?? null;

  const temperatureLimit = limit("machine.temperature_c");
  const vibrationLimit = limit("machine.vibration_mm_s");

  return (
    <section className="card" aria-labelledby="factory-status">
      <h2 id="factory-status" className="card-title flex items-center justify-between">
        <span>Factory status</span>
        {thresholds.length > 0 && (
          <span className="font-normal normal-case tracking-normal text-slate-400">
            limits from <span className="mono">rule_thresholds</span>
          </span>
        )}
      </h2>

      {machines.length === 0 ? (
        <p className="px-4 py-6 text-sm text-slate-500">
          No machine data. The MES backend is not answering.
        </p>
      ) : (
        <ul className="grid grid-cols-1 divide-y divide-slate-200/70 sm:grid-cols-2 sm:divide-y-0 lg:grid-cols-5">
          {machines.map((machine) => (
            <li key={machine.machine_id} className="px-4 py-3 sm:border-r sm:border-slate-200/70 sm:last:border-r-0">
              <div className="flex items-center justify-between gap-2">
                <span className="mono font-semibold text-slate-900">{machine.machine_id}</span>
                <span className={`pill ${machineTone(machine.status)}`}>{machine.status}</span>
              </div>

              <p className="mt-0.5 truncate text-[11px] text-slate-500" title={machine.machine_name}>
                {machine.machine_name}
                {machine.current_job ? ` · ${machine.current_job}` : ""}
              </p>

              <dl className="mt-2.5 space-y-1 text-[12px]">
                <Reading
                  label="Temp"
                  value={machine.temperature_c}
                  unit="°C"
                  limit={temperatureLimit}
                />
                <Reading
                  label="Vibration"
                  value={machine.vibration_mm_s}
                  unit="mm/s"
                  limit={vibrationLimit}
                />
                <Reading label="Utilisation" value={machine.utilization_pct} unit="%" limit={null} />
              </dl>
            </li>
          ))}
        </ul>
      )}
    </section>
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
  const over = value !== null && limit !== null && value >= limit;

  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="text-slate-500">{label}</dt>
      <dd className={`tabular ${readingTone(value, limit)}`}>
        {value === null ? (
          <span className="text-slate-400" title="No reading — the sensor is offline, not zero.">
            — no reading
          </span>
        ) : (
          <>
            {formatNumber(value)} {unit}
            {over && limit !== null && (
              <span className="ml-1 text-[11px] font-normal text-red-500">
                ≥ {formatNumber(limit)}
              </span>
            )}
          </>
        )}
      </dd>
    </div>
  );
}
