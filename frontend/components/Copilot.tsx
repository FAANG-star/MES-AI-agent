"use client";

import { useCallback, useRef, useState } from "react";

import { readSSE } from "@/lib/sse";
import { mergeSteps, runStage, STAGE_LABEL, type PanelStep } from "@/lib/steps";
import type {
  AgentRun,
  AnswerEvent,
  ExecutedStep,
  StepEvent,
  UnderstandingEvent,
} from "@/lib/types";

import { Answer } from "./Answer";
import { Composer } from "./Composer";
import { Analysis, Calculation, Health } from "./Evidence";
import { Sources } from "./Sources";
import { Timeline } from "./Timeline";

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
  const active = busy || run !== null || state.understanding !== null || state.error !== null;
  const stage = STAGE_LABEL[runStage(state.understanding !== null, state.steps, state.answer !== null)];

  return (
    <div className={active ? "space-y-8" : ""}>
      <Composer onAsk={ask} onCancel={cancel} busy={busy} compact={active} stage={busy ? stage : null} />

      {active && (
        <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_360px]">
          <div className="min-w-0 space-y-8">
            <div className="panel p-6 sm:p-8">
              <Answer
                run={run}
                understanding={state.understanding}
                streamed={state.answer}
                error={state.error}
                busy={busy}
                onAsk={ask}
              />
            </div>

            {run && (run.capacity || run.health.length > 0 || run.analysis) && (
              <div className="space-y-8 px-1">
                <Calculation run={run} />
                <Health run={run} />
                <Analysis run={run} />
              </div>
            )}
          </div>

          <div className="space-y-5">
            <Timeline
              steps={steps}
              toolCalls={run ? run.tool_call_count : null}
              busy={busy}
              settled={run !== null}
            />
            {run && <Sources sources={run.sources} />}
          </div>
        </div>
      )}
    </div>
  );
}
