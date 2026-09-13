import { formatElapsed, STEP_KIND } from "@/lib/format";
import type { PanelStep } from "@/lib/steps";

/**
 * "AI Analysis Steps" — the panel the whole demo is built around (brief §9).
 *
 * It answers the only question a factory manager really has about an AI
 * answer: where did that number come from. Each row says which of the three
 * kinds of work it was — a controlled MES read, deterministic arithmetic, or
 * the model writing prose — and every row can be opened to show the exact
 * arguments it ran with.
 *
 * The rows appear before they run. A plan that is only shown afterwards is a
 * story about what happened; a plan shown first is a commitment.
 */
export function AnalysisSteps({
  steps,
  toolCalls,
  busy,
  settled,
}: {
  steps: PanelStep[];
  toolCalls: number | null;
  busy: boolean;
  /** True once a run has finished — an empty panel then means something. */
  settled: boolean;
}) {
  if (steps.length === 0) {
    return (
      <section className="card" aria-labelledby="steps">
        <h2 id="steps" className="card-title">
          AI analysis steps
        </h2>
        <p className="px-4 py-6 text-sm text-slate-500">
          {settled
            ? // The empty panel is the evidence here, not a missing feature.
              "No step ran. The request was settled before the agent reached the factory, so no tool was called and no row was read."
            : "Ask a question and the agent\u2019s plan appears here before it runs."}
        </p>
      </section>
    );
  }

  return (
    <section className="card" aria-labelledby="steps">
      <h2 id="steps" className="card-title flex items-center justify-between">
        <span>AI analysis steps</span>
        {toolCalls !== null && (
          <span
            className="font-normal normal-case tracking-normal text-slate-400"
            title="Controlled MES calls. Calculations and phrasing are not tool calls and are not counted."
          >
            {toolCalls} MES tool {toolCalls === 1 ? "call" : "calls"}
          </span>
        )}
      </h2>

      <ol className="divide-y divide-slate-200/70">
        {steps.map((step) => (
          <Row key={step.step} step={step} busy={busy} />
        ))}
      </ol>
    </section>
  );
}

function Row({ step, busy }: { step: PanelStep; busy: boolean }) {
  const kind = STEP_KIND[step.kind];
  const pending = step.status === "pending";
  const running = pending && busy;
  const hasDetail =
    Object.keys(step.arguments).length > 0 ||
    step.bindingNotes.length > 0 ||
    step.sources.length > 0 ||
    step.note !== null;

  return (
    <li className={`step-in px-4 py-3 ${pending ? "opacity-60" : ""}`}>
      <div className="flex items-start gap-3">
        <Marker status={step.status} index={step.step} running={running} />

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <span className="text-[13px] font-medium text-slate-900">{step.title}</span>
            <span className="mono text-slate-400">{step.tool}</span>
            <span
              className={`ml-auto pill ${
                step.kind === "tool"
                  ? "bg-sky-50 text-sky-700 ring-sky-600/20"
                  : step.kind === "engine"
                    ? "bg-violet-50 text-violet-700 ring-violet-600/20"
                    : "bg-slate-100 text-slate-600 ring-slate-500/20"
              }`}
              title={kind.hint}
            >
              {kind.label}
            </span>
          </div>

          <p className="mt-1 text-[13px] leading-relaxed text-slate-600">
            {pending ? <span className="italic text-slate-500">{step.summary}</span> : step.summary}
          </p>

          {step.missing.length > 0 && (
            <p className="mt-1 text-[12px] text-amber-700">
              missing: <span className="mono">{step.missing.join(", ")}</span>
            </p>
          )}

          {step.warnings.map((warning) => (
            <p key={warning} className="mt-1 text-[12px] text-slate-500">
              {warning}
            </p>
          ))}

          {hasDetail && !pending && (
            <details className="group mt-1.5">
              <summary className="cursor-pointer list-none text-[11px] text-slate-400 transition hover:text-slate-600">
                <span className="group-open:hidden">show call detail</span>
                <span className="hidden group-open:inline">hide call detail</span>
              </summary>

              <div className="mt-2 space-y-2 rounded-md bg-slate-50 p-3 text-[12px]">
                {Object.keys(step.arguments).length > 0 && (
                  <Detail label="arguments">
                    <code className="mono text-slate-700">{JSON.stringify(step.arguments)}</code>
                  </Detail>
                )}

                {step.bindingNotes.length > 0 && (
                  <Detail label="from earlier steps">
                    <ul className="space-y-0.5">
                      {step.bindingNotes.map((note) => (
                        <li key={note} className="mono text-slate-700">
                          {note}
                        </li>
                      ))}
                    </ul>
                  </Detail>
                )}

                {step.sources.length > 0 && (
                  <Detail label="tables read">
                    <span className="mono text-slate-700">{step.sources.join(", ")}</span>
                  </Detail>
                )}

                {step.note && <p className="text-slate-500">{step.note}</p>}

                <p className="text-slate-400">took {formatElapsed(step.elapsed_ms)}</p>
              </div>
            </details>
          )}
        </div>
      </div>
    </li>
  );
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap gap-x-2">
      <span className="w-32 shrink-0 text-slate-400">{label}</span>
      <div className="min-w-0 flex-1 break-all">{children}</div>
    </div>
  );
}

function Marker({
  status,
  index,
  running,
}: {
  status: PanelStep["status"];
  index: number;
  running: boolean;
}) {
  const base =
    "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold ring-1 ring-inset tabular";

  if (status === "ok") {
    return (
      <span className={`${base} bg-emerald-50 text-emerald-700 ring-emerald-600/25`} aria-label="done">
        ✓
      </span>
    );
  }
  if (status === "failed" || status === "not_implemented") {
    return (
      <span className={`${base} bg-red-50 text-red-700 ring-red-600/25`} aria-label={status}>
        !
      </span>
    );
  }
  if (status === "skipped") {
    return (
      <span className={`${base} bg-slate-100 text-slate-400 ring-slate-400/30`} aria-label="skipped">
        –
      </span>
    );
  }
  return (
    <span
      className={`${base} bg-white text-slate-400 ring-slate-300 ${running ? "animate-pulse" : ""}`}
      aria-label="pending"
    >
      {index}
    </span>
  );
}
