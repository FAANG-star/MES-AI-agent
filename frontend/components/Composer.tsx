"use client";

import { useEffect, useRef, useState } from "react";

/**
 * The five demo scenarios and the reliability probes from
 * `docs/04-demo-scenarios.md`. The probes are here on purpose: the answers
 * worth showing a factory manager include the refusal, the clarification and
 * the rejection, and nobody thinks to type those.
 */
const SCENARIOS = [
  "How many A12 parts can we produce this week?",
  "Can CNC-03 continue production today?",
  "Which CNC machine is limiting A12 production?",
  "Why was A12 production lower yesterday?",
  "Which machine needs maintenance attention?",
];

const PROBES = [
  { q: "How many B20 parts can we produce tomorrow?", note: "missing data" },
  { q: "How many A12?", note: "ambiguous" },
  { q: "Write me a story.", note: "out of scope" },
];

/**
 * The question box. Large and alone on an idle page — the page has one
 * purpose — and compact once there is an answer to read beneath it.
 */
export function Composer({
  onAsk,
  onCancel,
  busy,
  compact,
  stage,
}: {
  onAsk: (question: string) => void;
  onCancel: () => void;
  busy: boolean;
  compact: boolean;
  stage: string | null;
}) {
  const [value, setValue] = useState("");
  const input = useRef<HTMLInputElement>(null);

  // "/" focuses the box from anywhere, the way a command bar does.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const typing = event.target instanceof HTMLInputElement;
      if (event.key === "/" && !typing) {
        event.preventDefault();
        input.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const submit = (question: string) => {
    const trimmed = question.trim();
    if (!trimmed || busy) return;
    setValue(trimmed);
    onAsk(trimmed);
  };

  return (
    <div className={compact ? "" : "mx-auto max-w-3xl pt-10 text-center sm:pt-16"}>
      {!compact && (
        <div className="rise">
          <p className="eyebrow">Local model · Read-only MES · Validated answers</p>
          <h1 className="mt-5 text-[40px] font-semibold leading-[1.05] tracking-[-0.035em] text-fg sm:text-[56px]">
            Ask the factory.
          </h1>
          <p className="mx-auto mt-4 max-w-xl text-[16px] leading-relaxed text-fg-2">
            Every figure is read from the MES, calculated by the engine, and checked against the
            data before you see it.
          </p>
        </div>
      )}

      <form
        onSubmit={(event) => {
          event.preventDefault();
          submit(value);
        }}
        className={`rise group relative ${compact ? "" : "mt-9"}`}
      >
        <div
          className={`relative flex items-center overflow-hidden rounded-2xl border bg-raised/90 shadow-[0_1px_0_rgb(255_255_255/0.04)_inset,0_20px_60px_-20px_rgb(0_0_0/0.8)] transition-colors ${
            busy ? "border-accent/40" : "border-line-strong focus-within:border-accent/60"
          }`}
        >
          <svg
            aria-hidden
            viewBox="0 0 20 20"
            className="ml-5 h-[18px] w-[18px] shrink-0 text-fg-3"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
          >
            <circle cx="9" cy="9" r="6" />
            <path d="m13.5 13.5 4 4" strokeLinecap="round" />
          </svg>

          <label htmlFor="question" className="sr-only">
            Your question
          </label>
          <input
            ref={input}
            id="question"
            name="question"
            autoComplete="off"
            value={value}
            disabled={busy}
            onChange={(event) => setValue(event.target.value)}
            placeholder="How many A12 parts can we produce this week?"
            className={`min-w-0 flex-1 bg-transparent px-4 text-left text-fg outline-none placeholder:text-fg-3 disabled:text-fg-2 ${
              compact ? "h-14 text-[16px]" : "h-16 text-[17px]"
            }`}
          />

          {!busy && !value && (
            <kbd className="mr-3 hidden rounded-md border border-line-strong px-1.5 py-0.5 font-mono text-[11px] text-fg-3 sm:block">
              /
            </kbd>
          )}

          {busy ? (
            <button
              type="button"
              onClick={onCancel}
              className="mr-2 h-10 rounded-xl border border-line-strong px-4 text-[13px] font-medium text-fg-2 transition-colors hover:border-white/25 hover:text-fg"
            >
              Stop
            </button>
          ) : (
            <button
              type="submit"
              disabled={!value.trim()}
              className="mr-2 inline-flex h-10 items-center gap-2 rounded-xl bg-accent px-4 text-[14px] font-semibold text-canvas transition hover:brightness-110 disabled:bg-white/[0.06] disabled:text-fg-3"
            >
              Ask
              <span aria-hidden className="font-mono text-[12px] opacity-70">
                ↵
              </span>
            </button>
          )}

          {busy && (
            <span aria-hidden className="absolute inset-x-0 bottom-0 h-px overflow-hidden">
              <span className="sweep block h-px w-1/3 bg-gradient-to-r from-transparent via-accent to-transparent" />
            </span>
          )}
        </div>

        {busy && stage && (
          <p className="mt-3 text-left text-[13px] text-fg-2" aria-live="polite">
            <span className="mr-2 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-accent align-middle" />
            {stage}
          </p>
        )}
      </form>

      {!busy && (
        <div
          className={`rise flex gap-2 ${
            compact
              ? "-mx-6 mt-3 overflow-x-auto px-6 pb-1 [mask-image:linear-gradient(to_right,black_85%,transparent)] [scrollbar-width:none] [&>button]:shrink-0 [&>button]:whitespace-nowrap"
              : "mt-6 flex-wrap justify-center"
          }`}
        >
          {SCENARIOS.map((q) => (
            <button key={q} type="button" className="chip" onClick={() => submit(q)}>
              {q}
            </button>
          ))}
          {PROBES.map(({ q, note }) => (
            <button
              key={q}
              type="button"
              className="chip border-dashed"
              title={`Reliability probe — ${note}`}
              onClick={() => submit(q)}
            >
              {q}
              <span className="ml-2 font-mono text-[10px] uppercase tracking-wider text-fg-3">
                {note}
              </span>
            </button>
          ))}
        </div>
      )}

      {!compact && (
        <ol className="rise mx-auto mt-14 grid max-w-2xl grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line text-left sm:grid-cols-4">
          {[
            ["01", "Understand", "Local model reads the question"],
            ["02", "Read", "Controlled MES tools, read-only"],
            ["03", "Calculate", "Deterministic engine, no model"],
            ["04", "Validate", "Every figure checked against the data"],
          ].map(([n, title, body]) => (
            <li key={n} className="bg-canvas/90 px-4 py-3.5">
              <span className="font-mono text-[11px] text-accent">{n}</span>
              <p className="mt-1 text-[13px] font-medium text-fg">{title}</p>
              <p className="mt-0.5 text-[12px] leading-snug text-fg-3">{body}</p>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
