import { agentMode, datasetWarning } from "@/lib/format";
import { formatDay } from "@/lib/timezone";
import type { Health } from "@/lib/types";

import { ThemeToggle } from "./ThemeToggle";
import { TimeZonePicker } from "./TimeZonePicker";
import { Dot } from "./ui";

/**
 * Three claims worth making before anyone asks anything: the model runs
 * locally, the tool connection cannot write, and whose clock the answers use.
 * Each is read from `/api/health`, so the indicator reports the live system.
 */
export function TopBar({ health }: { health: Health | null }) {
  const degraded = agentMode(health) === "rules";

  return (
    // `relative z-40`: the blur gives the header its own stacking context, and the
    // panels below (also blurred) would otherwise paint over the time-zone menu
    // that drops out of it — the list was visible but could not be clicked.
    <header className="relative z-40 border-b border-line bg-canvas/70 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-[1200px] items-center gap-6 px-6">
        <div className="flex items-center gap-2.5">
          <Mark />
          <span className="whitespace-nowrap text-[14px] font-semibold tracking-tight">MES Copilot</span>
          <span className="hidden text-[13px] text-fg-3 sm:inline">Smart CNC Factory</span>
        </div>

        <div className="ml-auto flex items-center gap-4 text-[12px] text-fg-2 sm:gap-5">
          {health ? (
            <>
              <span
                className="hidden items-center gap-2 lg:inline-flex"
                title={
                  degraded
                    ? "No model is reachable. Understanding falls back to deterministic rules; figures are unaffected."
                    : "The language model runs inside this environment. Factory data never leaves it."
                }
              >
                <Dot tone={degraded ? "warn" : "ok"} />
                {degraded ? "Rules only" : "Local model"}
              </span>
              <span
                className="hidden items-center gap-2 lg:inline-flex"
                title={`Tools connect as ${health.database.user}, which can only read.`}
              >
                <Dot tone={health.database.read_only ? "ok" : "bad"} />
                Read-only MES
              </span>
              {/*
                Amber, next to the rehearsal badge and for the same reason: the
                figures are right and the day is wrong, which is the hardest
                kind of wrong to notice. The fix is one command, so the badge
                names it.
              */}
              {datasetWarning(health) && (
                <span
                  className="inline-flex items-center gap-2 whitespace-nowrap rounded-full border border-warn/40 bg-warn/10 px-2.5 py-1 text-warn"
                  title={health.dataset?.note ?? undefined}
                >
                  <Dot tone="warn" />
                  {datasetWarning(health)} · run make db-seed
                </span>
              )}
              {health.factory.pinned && (
                <span
                  className="inline-flex items-center gap-2 whitespace-nowrap rounded-full border border-warn/40 bg-warn/10 px-2.5 py-1 text-warn"
                  title="FACTORY_TODAY is set on the backend: answers use this date, not the real one. Unset it after the rehearsal."
                >
                  <Dot tone="warn" />
                  Rehearsal · {formatDay(health.factory.today)}
                </span>
              )}
              <TimeZonePicker />
            </>
          ) : (
            <span className="inline-flex items-center gap-2 text-bad">
              <Dot tone="bad" /> Backend unreachable
            </span>
          )}
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}

function Mark() {
  return (
    <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden>
      <rect width="32" height="32" rx="8" fill="#ff7a2f" />
      <circle cx="16" cy="16" r="8" fill="none" stroke="#0a0b0d" strokeWidth="2.4" />
      <circle cx="16" cy="16" r="2.6" fill="#0a0b0d" />
    </svg>
  );
}
