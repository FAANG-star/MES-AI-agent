"use client";

import { formatElapsed, formatWindow, headlineParts, humanise } from "@/lib/format";
import { formatDay, wallClock, zoneCity } from "@/lib/timezone";
import type { AgentRun, AnswerEvent, UnderstandingEvent } from "@/lib/types";

import { useTime } from "./TimeProvider";
import { Badge, Eyebrow } from "./ui";

/**
 * What the factory manager reads.
 *
 * The figure the engine produced comes first and largest, then the sentence
 * the model wrote about it, then the facts about how both were checked. That
 * order is the argument: the number is the result, the prose describes it.
 *
 * A refusal, a clarification and a rejection each get their own form. They
 * are answers the client asked to see, not errors, and styling them as errors
 * would misrepresent a system doing exactly what it should.
 */
export function Answer({
  run,
  understanding,
  streamed,
  error,
  busy,
  onAsk,
}: {
  run: AgentRun | null;
  understanding: UnderstandingEvent | null;
  streamed: AnswerEvent | null;
  error: string | null;
  busy: boolean;
  onAsk: (question: string) => void;
}) {
  if (error) {
    return (
      <div className="rise">
        <Eyebrow className="!text-bad">The run did not complete</Eyebrow>
        <p className="mt-3 text-[22px] leading-snug tracking-tight text-fg">{error}</p>
        <p className="mt-3 text-[14px] text-fg-3">
          Nothing was answered from a partial result. The factory figures are unaffected.
        </p>
      </div>
    );
  }

  if (!run) {
    // Mid-run: the answer event can land before the full run does.
    return (
      <div className="rise">
        <Eyebrow>{understanding ? humanise(understanding.intent) : "Working"}</Eyebrow>
        {understanding?.rewritten_question && (
          <p className="mt-3 max-w-[60ch] text-[22px] leading-snug tracking-tight text-fg-2">
            {understanding.rewritten_question}
          </p>
        )}
        {streamed ? (
          <p className="mt-5 max-w-[62ch] text-[18px] leading-relaxed text-fg">{streamed.answer}</p>
        ) : (
          busy && <Skeleton />
        )}
      </div>
    );
  }

  const touchedData = run.steps.length > 0;
  const rewritten =
    run.rewritten_question && run.rewritten_question !== run.question
      ? run.rewritten_question
      : null;

  if (run.status === "rejected_out_of_domain") {
    return (
      <div className="rise">
        <Eyebrow>Outside this assistant&rsquo;s scope</Eyebrow>
        <p className="mt-3 max-w-[40ch] text-[28px] font-medium leading-tight tracking-tight text-fg">
          {run.answer}
        </p>
        <div className="mt-6 flex flex-wrap gap-2">
          <Badge tone="ok" title="Acceptance criterion 7: a rejected request reads nothing.">
            No tool called · no factory data read
          </Badge>
        </div>
      </div>
    );
  }

  if (run.status === "clarify" && run.clarification) {
    return (
      <div className="rise">
        <Eyebrow>One detail first</Eyebrow>
        <p className="mt-3 max-w-[36ch] text-[28px] font-medium leading-tight tracking-tight text-fg">
          {run.clarification.question}
        </p>
        <p className="mt-3 text-[14px] text-fg-3">{run.clarification.because}</p>
        <div className="mt-6 flex flex-wrap gap-2">
          {run.clarification.options.map((option) => (
            <button
              key={option}
              type="button"
              disabled={busy}
              onClick={() => onAsk(`${run.question} ${option}`)}
              className="rounded-xl border border-line-strong bg-raised px-4 py-2.5 text-[14px] text-fg transition-colors hover:border-accent/60 hover:bg-accent-soft disabled:opacity-40"
            >
              {option}
            </button>
          ))}
        </div>
        <p className="mt-5 text-[13px] text-fg-3">
          No tool was called. The agent asked rather than choosing one of these for you.
        </p>
      </div>
    );
  }

  const refused = run.status === "refused_missing_data";
  const { figure, unit } = run.headline
    ? headlineParts(run.headline.value, run.headline.unit, run.headline.text)
    : { figure: "", unit: "" };

  return (
    <div className="rise">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <Eyebrow className={refused ? "!text-warn" : ""}>
          {refused ? "Cannot calculate" : run.headline?.label ?? humanise(run.intent)}
        </Eyebrow>
        <span className="font-mono text-[11px] text-fg-3 tabular" title="This run in the audit trail">
          {run.run_id.slice(0, 8)} · {formatElapsed(run.elapsed_ms)}
        </span>
      </div>

      {run.headline && !refused && (
        <p className="mt-2 flex items-baseline gap-3 leading-none">
          <span className="text-[56px] font-semibold tracking-[-0.045em] text-fg tabular sm:text-[72px]">
            {figure}
          </span>
          {unit && <span className="text-[22px] font-medium tracking-tight text-fg-3">{unit}</span>}
        </p>
      )}

      <p
        className={`max-w-[62ch] leading-relaxed ${
          run.headline && !refused ? "mt-5 text-[18px] text-fg-2" : "mt-3 text-[24px] tracking-tight text-fg"
        }`}
      >
        {run.answer}
      </p>

      {refused && run.missing_fields.length > 0 && (
        <ul className="mt-5 space-y-2">
          {run.missing_fields.map((field) => (
            <li
              key={`${field.entity}-${field.field}`}
              className="flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded-xl border border-warn/25 bg-warn/[0.06] px-4 py-3"
            >
              <code className="font-mono text-[13px] text-warn">{field.field}</code>
              <span className="text-[13px] text-fg-2">{field.reason}</span>
            </li>
          ))}
        </ul>
      )}

      {rewritten && (
        <p className="mt-4 max-w-[62ch] text-[13px] leading-relaxed text-fg-3">
          <span className="text-fg-2">Interpreted as</span> &ldquo;{rewritten}&rdquo;
        </p>
      )}

      {touchedData && (
        <div className="mt-6 flex flex-wrap gap-2">
          <Badge
            tone={run.validation.grounded ? "ok" : "bad"}
            title={run.validation.note}
          >
            {run.validation.grounded ? "Validated against MES data" : "Not grounded"}
            {run.validation.retries > 0 && (
              <span className="text-fg-3">
                · {run.validation.retries} {run.validation.retries === 1 ? "rewrite" : "rewrites"}
              </span>
            )}
          </Badge>
          <Badge
            tone={run.answer_is_generated ? "accent" : "muted"}
            title={
              run.answer_is_generated
                ? "The local model wrote this sentence from the engine's figures."
                : "Composed from the tool results; the model's draft did not survive validation, or no model was available."
            }
          >
            {run.answer_is_generated ? "Phrased by local model" : "Composed from tool results"}
          </Badge>
          {run.window && (
            <Badge
              tone="muted"
              title={`${run.window.basis} Dates are the factory's calendar days (${run.window.timezone}).`}
            >
              <span className="text-fg-3">Factory days</span>
              <span className="font-mono tabular">
                {formatWindow(run.window.start, run.window.end, run.window.days)}
              </span>
            </Badge>
          )}
        </div>
      )}

      {run.window && <DayNotice factoryZone={run.window.timezone} />}

      {run.bottleneck && (
        <div
          role="note"
          aria-label="Bottleneck"
          className="mt-7 flex flex-wrap items-baseline gap-x-4 gap-y-1 rounded-xl border border-accent/25 bg-accent-soft px-4 py-3"
        >
          <span className="eyebrow !text-accent">Bottleneck</span>
          <span className="font-mono text-[15px] font-medium text-fg">{run.bottleneck.machine_id}</span>
          <span className="text-[14px] text-fg-2">{run.bottleneck.reason}</span>
        </div>
      )}

      {run.notes.length > 0 && (
        <details className="group mt-5">
          <summary className="inline-flex cursor-pointer list-none items-center gap-1 font-mono text-[11px] text-fg-3 transition-colors hover:text-fg-2">
            <span className="transition-transform group-open:rotate-90">›</span>
            {run.notes.length} run {run.notes.length === 1 ? "note" : "notes"}
          </summary>
          <ul className="mt-2 space-y-1 border-l border-line pl-3">
            {run.notes.map((note) => (
              <li key={note} className="text-[12px] leading-relaxed text-fg-3">
                {note}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

/**
 * Said only when it matters: the viewer's calendar day is not the factory's.
 *
 * A manager in New York at 22:00 on Sunday asking about "today" gets the
 * factory's Monday — correctly, because the factory in Tokyo is already running
 * Monday's shifts. That is right, and it is surprising, so the answer says it
 * out loud instead of leaving the dates to be misread.
 */
function DayNotice({ factoryZone }: { factoryZone: string }) {
  const { viewerZone, now } = useTime();
  if (!viewerZone || viewerZone === factoryZone) return null;

  const factory = wallClock(now, factoryZone);
  const viewer = wallClock(now, viewerZone);
  if (factory.date === viewer.date) return null;

  return (
    <p className="mt-4 flex max-w-[62ch] gap-2 text-[13px] leading-relaxed text-fg-2">
      <svg viewBox="0 0 16 16" className="mt-[3px] h-3.5 w-3.5 shrink-0 text-accent" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden>
        <circle cx="8" cy="8" r="6" />
        <path d="M8 4.8V8l2.2 1.4" strokeLinecap="round" />
      </svg>
      <span>
        It is <span className="text-fg">{formatDay(viewer.date)}</span> where you are ({zoneCity(viewerZone)}).
        Days in this answer are the factory&rsquo;s — it is{" "}
        {factory.date > viewer.date ? "already " : "still "}
        <span className="text-fg">{formatDay(factory.date)}</span> in {zoneCity(factoryZone)}.
      </span>
    </p>
  );
}

function Skeleton() {
  return (
    <div className="mt-6 space-y-3" aria-hidden>
      <div className="h-14 w-56 animate-pulse rounded-lg bg-tint/[0.06]" />
      <div className="h-4 w-full max-w-lg animate-pulse rounded bg-tint/[0.05]" />
      <div className="h-4 w-4/5 max-w-md animate-pulse rounded bg-tint/[0.05]" />
    </div>
  );
}
