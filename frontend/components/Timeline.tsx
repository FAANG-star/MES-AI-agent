import { formatElapsed, STEP_KIND } from "@/lib/format";
import type { PanelStep } from "@/lib/steps";
import type { StepKind } from "@/lib/types";

import { Eyebrow } from "./ui";

/**
 * AI Analysis Steps (brief §9), as a timeline.
 *
 * The shape of each marker says what kind of work the row was — a circle for
 * a controlled MES read, a diamond for deterministic arithmetic, a ring for
 * the model writing prose — because that distinction is the demo's central
 * claim and should be readable at a glance, not only in a label.
 */
export function Timeline({
  steps,
  toolCalls,
  busy,
  settled,
}: {
  steps: PanelStep[];
  toolCalls: number | null;
  busy: boolean;
  settled: boolean;
}) {
  return (
    <aside className="panel p-5">
      <div className="flex items-baseline justify-between gap-3">
        <Eyebrow>Analysis steps</Eyebrow>
        {toolCalls !== null && (
          <span
            className="font-mono text-[11px] text-fg-3 tabular"
            title="Controlled MES calls. Calculation and phrasing are not tool calls."
          >
            {steps.length} steps · {toolCalls} MES {toolCalls === 1 ? "call" : "calls"}
          </span>
        )}
      </div>

      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-fg-3">
        {(["tool", "engine", "llm"] as StepKind[]).map((kind) => (
          <span key={kind} className="inline-flex items-center gap-1.5" title={STEP_KIND[kind].hint}>
            <Marker kind={kind} status="ok" />
            {STEP_KIND[kind].label}
          </span>
        ))}
      </div>

      {steps.length === 0 ? (
        <p className="mt-6 text-[13px] leading-relaxed text-fg-3">
          {settled
            ? "No step ran. The request was settled before the agent reached the factory — no tool was called and no row was read."
            : busy
              ? "Planning…"
              : "The agent’s plan appears here, then fills in as each step runs."}
        </p>
      ) : (
        <ol className="mt-5">
          {steps.map((step, index) => (
            <Row
              key={step.step}
              step={step}
              last={index === steps.length - 1}
              busy={busy}
            />
          ))}
        </ol>
      )}
    </aside>
  );
}

function Row({ step, last, busy }: { step: PanelStep; last: boolean; busy: boolean }) {
  const pending = step.status === "pending";
  const skipped = step.status === "skipped";
  const hasDetail =
    Object.keys(step.arguments).length > 0 || step.bindingNotes.length > 0 || step.sources.length > 0;

  return (
    <li className="rise relative flex gap-3.5 pb-5 last:pb-0">
      {!last && <span aria-hidden className="absolute left-[7px] top-5 bottom-0 w-px bg-line-strong" />}

      <span className="relative mt-[3px] flex h-[15px] w-[15px] shrink-0 items-center justify-center">
        <Marker kind={step.kind} status={step.status} pulse={pending && busy} />
      </span>

      <div className={`min-w-0 flex-1 ${pending || skipped ? "opacity-50" : ""}`}>
        <div className="flex items-baseline justify-between gap-3">
          <p className="text-[13px] font-medium leading-snug text-fg">{step.title}</p>
          {!pending && step.elapsed_ms > 0 && (
            <span className="shrink-0 font-mono text-[10px] text-fg-3 tabular">
              {formatElapsed(step.elapsed_ms)}
            </span>
          )}
        </div>

        <p className="mt-1 text-[12.5px] leading-relaxed text-fg-2">{step.summary}</p>

        {step.missing.length > 0 && (
          <p className="mt-1.5 font-mono text-[11px] text-warn">missing {step.missing.join(", ")}</p>
        )}

        {hasDetail && !pending && (
          <details className="group mt-1.5">
            <summary className="inline-flex cursor-pointer list-none items-center gap-1 font-mono text-[11px] text-fg-3 transition-colors hover:text-fg-2">
              <span className="transition-transform group-open:rotate-90">›</span>
              {step.tool}
            </summary>
            <dl className="mt-2 space-y-1.5 rounded-lg border border-line bg-canvas/60 p-3 font-mono text-[11px] leading-relaxed">
              {Object.keys(step.arguments).length > 0 && (
                <Detail label="args">{JSON.stringify(step.arguments)}</Detail>
              )}
              {step.bindingNotes.map((note) => (
                <Detail key={note} label="bound">
                  {note}
                </Detail>
              ))}
              {step.sources.length > 0 && <Detail label="read">{step.sources.join(", ")}</Detail>}
            </dl>
          </details>
        )}
      </div>
    </li>
  );
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3">
      <dt className="w-10 shrink-0 text-fg-3">{label}</dt>
      <dd className="min-w-0 break-all text-fg-2">{children}</dd>
    </div>
  );
}

function Marker({
  kind,
  status,
  pulse = false,
}: {
  kind: StepKind;
  status: PanelStep["status"];
  pulse?: boolean;
}) {
  if (status === "failed" || status === "not_implemented") {
    return <span className="h-2.5 w-2.5 rounded-full bg-bad" aria-label={status} />;
  }
  if (status === "pending") {
    return (
      <span
        className={`h-2.5 w-2.5 rounded-full border border-fg-3 ${pulse ? "animate-pulse" : ""}`}
        aria-label="pending"
      />
    );
  }
  if (status === "skipped") {
    return <span className="h-2.5 w-2.5 rounded-full border border-dashed border-fg-3" aria-label="skipped" />;
  }
  if (kind === "engine") {
    return <span className="h-2 w-2 rotate-45 bg-accent" aria-label="calculation" />;
  }
  if (kind === "llm") {
    return (
      <span className="flex h-2.5 w-2.5 items-center justify-center rounded-full border border-fg-2" aria-label="language model">
        <span className="h-1 w-1 rounded-full bg-fg-2" />
      </span>
    );
  }
  return <span className="h-2.5 w-2.5 rounded-full bg-fg" aria-label="MES tool" />;
}
