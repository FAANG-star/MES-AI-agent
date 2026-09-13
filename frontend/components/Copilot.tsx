"use client";

import { useCallback, useRef, useState } from "react";

import { readSSE } from "@/lib/sse";
import { mergeSteps, type PanelStep } from "@/lib/steps";
import type {
  AgentRun,
  AnswerEvent,
  ExecutedStep,
  StepEvent,
  UnderstandingEvent,
} from "@/lib/types";

import { AnalysisSteps } from "./AnalysisSteps";
import { AnswerCard } from "./AnswerCard";
import { AskBox } from "./AskBox";
import { AnalysisPanel, CalculationPanel, HealthPanel } from "./Evidence";
import { DataUsed } from "./DataUsed";

interface RunState {
  understanding: UnderstandingEvent | null;
  steps: ExecutedStep[];
  answer: AnswerEvent | null;
  run: AgentRun | null;
  error: string | null;
}

const EMPTY: RunState = { understanding: null, steps: [], answer: null, run: null, error: null };

/**
 * One question at a time, streamed.
 *
 * The run is consumed as server-sent events rather than waited for, because on
 * CPU the local model takes tens of seconds and a blank screen for that long
 * reads as a hang. The panel fills in the order the work actually happens: the
 * plan first, then each MES call as it returns, then the calculation, then the
 * sentence.
 *
 * State is replaced, never merged across questions. A second question that
 * inherited the first one's steps would be showing evidence for an answer that
 * is no longer on screen.
 */
export function Copilot() {
  const [state, setState] = useState<RunState>(EMPTY);
  const [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);

  const cancel = useCallback(() => {
    controller.current?.abort();
    controller.current = null;
    setBusy(false);
  }, []);

  const ask = useCallback(async (question: string) => {
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;

    setState(EMPTY);
    setBusy(true);

    try {
      const response = await fetch("/api/mes/ask/stream", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question }),
        signal: abort.signal,
      });

      if (!response.ok || !response.body) {
        const detail = await response
          .json()
          .then((body: { error?: string; detail?: string }) =>
            [body.error, body.detail].filter(Boolean).join(" "),
          )
          .catch(() => "");
        throw new Error(detail || `The backend answered ${response.status}.`);
      }

      await readSSE(
        response.body,
        (event, data) => {
          if (data === null) return;
          switch (event) {
            case "understanding":
              setState((s) => ({ ...s, understanding: data as UnderstandingEvent }));
              break;
            case "tool_result": {
              const step = data as StepEvent;
              setState((s) => ({
                ...s,
                // A step can only arrive once, but replacing by number rather
                // than appending keeps the panel correct if that ever changes.
                steps: [...s.steps.filter((e) => e.step !== step.step), step],
              }));
              break;
            }
            case "answer":
              setState((s) => ({ ...s, answer: data as AnswerEvent }));
              break;
            case "run":
              setState((s) => ({ ...s, run: data as AgentRun }));
              break;
            case "error":
              setState((s) => ({
                ...s,
                error: (data as { message?: string }).message ?? "The run failed.",
              }));
              break;
          }
        },
        abort.signal,
      );
    } catch (error) {
      if (abort.signal.aborted) return; // the user pressed Stop
      setState((s) => ({
        ...s,
        error: error instanceof Error ? error.message : "The run could not be started.",
      }));
    } finally {
      if (controller.current === abort) {
        controller.current = null;
        setBusy(false);
      }
    }
  }, []);

  const steps: PanelStep[] = mergeSteps(state.understanding?.plan ?? [], state.steps);
  const run = state.run;

  return (
    <div className="space-y-4">
      <AskBox onAsk={ask} busy={busy} onCancel={cancel} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        <div className="space-y-4 lg:col-span-3">
          <AnswerCard
            run={run}
            understanding={state.understanding}
            streamed={state.answer}
            busy={busy}
            error={state.error}
            onAsk={ask}
          />

          {run && <CalculationPanel run={run} />}
          {run && <HealthPanel run={run} />}
          {run && <AnalysisPanel run={run} />}
        </div>

        <div className="space-y-4 lg:col-span-2">
          <AnalysisSteps
            steps={steps}
            toolCalls={run ? run.tool_call_count : null}
            busy={busy}
            settled={run !== null}
          />
          {run && <DataUsed sources={run.sources} />}
        </div>
      </div>
    </div>
  );
}
