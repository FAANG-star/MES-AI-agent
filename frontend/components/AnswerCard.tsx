"use client";

import { formatElapsed, formatHeadline, formatWindow } from "@/lib/format";
import type { AgentRun, AnswerEvent, UnderstandingEvent } from "@/lib/types";

/**
 * What the factory manager reads.
 *
 * The card leads with the figure the engine produced, then the sentence the
 * model wrote about it, then the evidence. That order is the argument the
 * prototype is making: the number is the result, the prose is a description of
 * it, and both can be checked.
 *
 * Every terminal state gets a card of its own. A refusal and a rejection are
 * answers too — they are the two the client asked to see (brief §11, §12) —
 * and rendering them as errors would misrepresent a system working correctly.
 */
export function AnswerCard({
  run,
  understanding,
  streamed,
  busy,
  error,
  onAsk,
}: {
  run: AgentRun | null;
  understanding: UnderstandingEvent | null;
  streamed: AnswerEvent | null;
  busy: boolean;
  error: string | null;
  onAsk: (question: string) => void;
}) {
  if (error) {
    return (
      <Shell tone="error" title="The run did not complete">
        <p className="text-[15px] leading-relaxed text-slate-700">{error}</p>
        <p className="mt-2 text-[13px] text-slate-500">
          Nothing was answered from a partial result. The factory numbers are unaffected.
        </p>
      </Shell>
    );
  }

  if (!run && !understanding && !busy) {
    return (
      <Shell tone="idle" title="Answer">
        <p className="text-[15px] leading-relaxed text-slate-500">
          Ask a factory question. Every figure in the answer comes from the MES through the
          controlled tool layer, and is checked against it before you see it.
        </p>
      </Shell>
    );
  }

  const status = run?.status;
  const answer = run?.answer ?? streamed?.answer ?? "";
  const validation = run?.validation ?? streamed?.validation ?? null;
  const generated = run?.answer_is_generated ?? streamed?.answer_is_generated ?? false;
  const rewritten = run?.rewritten_question ?? understanding?.rewritten_question ?? null;
  const question = run?.question ?? understanding?.rewritten_question ?? "";
  const window = run?.window ?? understanding?.window ?? null;

  // A rejection and a clarification are decided before any tool runs, so there
  // is nothing for them to be grounded against.
  const touchedData = run !== null && run.steps.length > 0;

  const tone =
    status === "rejected_out_of_domain"
      ? "rejected"
      : status === "refused_missing_data"
        ? "refused"
        : status === "clarify"
          ? "clarify"
          : "answered";

  return (
    <Shell tone={tone} title={TITLES[tone]}>
      {/* FR-2: the rewrite is shown, not hidden. The manager sees how an
          incomplete question was read before reading the answer to it. */}
      {rewritten && rewritten !== question && (
        <p className="mb-3 border-l-2 border-slate-200 pl-3 text-[13px] leading-relaxed text-slate-500">
          <span className="font-medium text-slate-600">Interpreted as:</span> {rewritten}
        </p>
      )}

      {run?.headline && (
        <div className="mb-3">
          <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500">
            {run.headline.label}
          </p>
          <p className="mt-0.5 text-[34px] font-semibold leading-none tracking-tight text-slate-900 tabular">
            {formatHeadline(run.headline.value, run.headline.unit, run.headline.text)}
          </p>
        </div>
      )}

      {answer ? (
        <p className="whitespace-pre-line text-[15px] leading-relaxed text-slate-800">{answer}</p>
      ) : (
        <Working busy={busy} understanding={understanding} />
      )}

      {run?.clarification && (
        <div className="mt-4">
          <p className="text-[13px] text-slate-500">{run.clarification.because}</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {run.clarification.options.map((option) => (
              <button
                key={option}
                type="button"
                className="chip"
                disabled={busy}
                onClick={() => onAsk(`${run.question} ${option}`)}
              >
                {option}
              </button>
            ))}
          </div>
          <p className="mt-2 text-[12px] text-slate-400">
            No tool was called. The agent asked instead of choosing one of these for you.
          </p>
        </div>
      )}

      {run && run.missing_fields.length > 0 && (
        <ul className="mt-4 space-y-1.5 rounded-md bg-amber-50 p-3 text-[13px] ring-1 ring-inset ring-amber-600/20">
          {run.missing_fields.map((field) => (
            <li key={`${field.entity}-${field.field}`}>
              <span className="mono font-medium text-amber-900">{field.field}</span>
              <span className="text-amber-800"> — {field.reason}</span>
            </li>
          ))}
        </ul>
      )}

      {run?.bottleneck && (
        <div className="mt-4 rounded-md bg-slate-50 p-3 ring-1 ring-inset ring-slate-200">
          <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500">
            Bottleneck
          </p>
          <p className="mt-1 text-[14px] text-slate-800">
            <span className="mono font-semibold">{run.bottleneck.machine_id}</span> —{" "}
            {run.bottleneck.reason}
          </p>
        </div>
      )}

      {run && (
        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-slate-200/70 pt-3 text-[12px] text-slate-500">
          {touchedData ? (
            validation && (
              <ValidationBadge
                grounded={validation.grounded}
                retries={validation.retries}
                note={validation.note}
              />
            )
          ) : (
            <span
              className="pill bg-slate-100 text-slate-600 ring-slate-500/20"
              title="Acceptance criterion 7: a request that is turned away reads nothing."
            >
              no factory data was read
            </span>
          )}

          {touchedData && (
            <span
              title={
                generated
                  ? "The local model wrote this sentence from the engine's figures."
                  : "Composed from the tool results. The model's draft did not survive validation, or no model was available."
              }
            >
              {generated ? "phrased by the local model" : "composed from tool results"}
            </span>
          )}

          {window && touchedData && (
            <span className="tabular" title={window.basis}>
              {formatWindow(window.start, window.end, window.days)}
            </span>
          )}

          <span className="tabular">{formatElapsed(run.elapsed_ms)}</span>

          <span className="mono text-slate-400" title="This run in the audit trail">
            {run.run_id.slice(0, 8)}
          </span>
        </div>
      )}

      {run?.notes.map((note) => (
        <p key={note} className="mt-2 text-[12px] text-amber-700">
          {note}
        </p>
      ))}
    </Shell>
  );
}

// Keyed by tone, which is what the lookup uses. Keying these by run status
// while `tone` indexed them left the rejection card with no heading at all.
const TITLES: Record<string, string> = {
  answered: "Answer",
  clarify: "One thing first",
  refused: "Cannot calculate this",
  rejected: "Outside this assistant's domain",
  idle: "Answer",
  error: "The run did not complete",
};

const TONES: Record<string, string> = {
  answered: "border-t-4 border-t-sky-600",
  clarify: "border-t-4 border-t-slate-400",
  refused: "border-t-4 border-t-amber-500",
  rejected: "border-t-4 border-t-slate-500",
  error: "border-t-4 border-t-red-500",
  idle: "border-t-4 border-t-slate-200",
};

function Shell({
  tone,
  title,
  children,
}: {
  tone: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className={`card ${TONES[tone] ?? TONES.idle}`} aria-labelledby="answer">
      <h2 id="answer" className="card-title">
        {title}
      </h2>
      <div className="p-4">{children}</div>
    </section>
  );
}

/**
 * What is happening while the model thinks.
 *
 * On CPU the explanation call alone takes tens of seconds. Saying which stage
 * the run is in — and that the figures are already settled — is the difference
 * between a considered system and a hung one.
 */
function Working({
  busy,
  understanding,
}: {
  busy: boolean;
  understanding: UnderstandingEvent | null;
}) {
  if (!busy) return null;

  return (
    <p className="flex items-center gap-2 text-[15px] text-slate-500">
      <span className="inline-flex gap-1" aria-hidden>
        <Dot delay="0ms" />
        <Dot delay="150ms" />
        <Dot delay="300ms" />
      </span>
      {understanding
        ? "Running the plan, then writing the answer from the figures it returns."
        : "Reading the question and planning the MES calls."}
    </p>
  );
}

function Dot({ delay }: { delay: string }) {
  return (
    <span
      className="h-1.5 w-1.5 animate-pulse rounded-full bg-slate-400"
      style={{ animationDelay: delay }}
    />
  );
}

/**
 * FR-7, on screen.
 *
 * "Grounded" means every figure in the sentence was found in the retrieved
 * data *and* the run's principal finding is stated. A retry means the first
 * draft failed and was rewritten with the fault named.
 */
function ValidationBadge({
  grounded,
  retries,
  note,
}: {
  grounded: boolean;
  retries: number;
  note: string;
}) {
  return (
    <span
      className={`pill ${
        grounded
          ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20"
          : "bg-red-50 text-red-700 ring-red-600/20"
      }`}
      title={note}
    >
      {grounded ? "✓ validated against the data" : "not grounded"}
      {retries > 0 && <span className="font-normal opacity-75">· {retries} retry</span>}
    </span>
  );
}
