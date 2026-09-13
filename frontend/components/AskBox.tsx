"use client";

import { useState } from "react";

/**
 * The five demo scenarios and the reliability probes, straight from
 * `docs/04-demo-scenarios.md`.
 *
 * They are one click away because the interesting cases are the ones nobody
 * thinks to type: the question that must be refused, the one that must be
 * clarified, the one that must be rejected. A demo that only ever shows the
 * happy path proves the least interesting half of the system.
 */
const SCENARIOS: { question: string; note: string }[] = [
  { question: "How many A12 parts can we produce this week?", note: "S1 · capacity (hero)" },
  { question: "Can CNC-03 continue production today?", note: "S2 · machine health" },
  { question: "Which CNC machine is limiting A12 production?", note: "S3 · bottleneck" },
  { question: "Why was A12 production lower yesterday?", note: "S4 · analysis" },
  { question: "Which machine needs maintenance attention?", note: "S5 · maintenance" },
];

const PROBES: { question: string; note: string }[] = [
  { question: "How many B20 parts can we produce tomorrow?", note: "R3 · must refuse" },
  { question: "How many A12?", note: "R2 · must clarify" },
  { question: "What is the status of CNC-09?", note: "R5 · unknown machine" },
  { question: "Write me a story.", note: "R4 · out of domain" },
];

export function AskBox({
  onAsk,
  busy,
  onCancel,
}: {
  onAsk: (question: string) => void;
  busy: boolean;
  onCancel: () => void;
}) {
  const [value, setValue] = useState("");

  const submit = (question: string) => {
    const trimmed = question.trim();
    if (!trimmed || busy) return;
    setValue(trimmed);
    onAsk(trimmed);
  };

  return (
    <section className="card" aria-labelledby="ask">
      <h2 id="ask" className="card-title">
        Ask the factory
      </h2>

      <div className="p-4">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            submit(value);
          }}
          className="flex flex-col gap-2 sm:flex-row"
        >
          <label htmlFor="question" className="sr-only">
            Your question
          </label>
          <input
            id="question"
            name="question"
            type="text"
            autoComplete="off"
            value={value}
            disabled={busy}
            onChange={(event) => setValue(event.target.value)}
            placeholder="How many A12 parts can we produce this week?"
            className="min-w-0 flex-1 rounded-md border border-slate-300 bg-white px-3.5 py-2.5
                       text-[15px] shadow-sm outline-none transition
                       placeholder:text-slate-400 focus:border-sky-500 focus:ring-2
                       focus:ring-sky-500/20 disabled:bg-slate-50 disabled:text-slate-500"
          />

          {busy ? (
            <button
              type="button"
              onClick={onCancel}
              className="rounded-md border border-slate-300 bg-white px-5 py-2.5 text-sm font-medium
                         text-slate-700 transition hover:bg-slate-50"
            >
              Stop
            </button>
          ) : (
            <button
              type="submit"
              disabled={!value.trim()}
              className="rounded-md bg-slate-900 px-6 py-2.5 text-sm font-semibold text-white
                         shadow-sm transition hover:bg-slate-800 disabled:cursor-not-allowed
                         disabled:bg-slate-300"
            >
              Ask
            </button>
          )}
        </form>

        <Examples title="Demo scenarios" items={SCENARIOS} busy={busy} onPick={submit} />
        <Examples title="Reliability" items={PROBES} busy={busy} onPick={submit} />
      </div>
    </section>
  );
}

function Examples({
  title,
  items,
  busy,
  onPick,
}: {
  title: string;
  items: { question: string; note: string }[];
  busy: boolean;
  onPick: (question: string) => void;
}) {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-1.5">
      <span className="mr-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-400">
        {title}
      </span>
      {items.map((item) => (
        <button
          key={item.question}
          type="button"
          className="chip"
          disabled={busy}
          title={item.note}
          onClick={() => onPick(item.question)}
        >
          {item.question}
        </button>
      ))}
    </div>
  );
}
