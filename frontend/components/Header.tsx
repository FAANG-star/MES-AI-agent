import { factoryDate, factoryTime } from "@/lib/format";
import type { Health } from "@/lib/types";

/**
 * The claims worth making before a single question is asked.
 *
 * Each pill is a fact the demo turns on: the model runs locally, the tool
 * connection cannot write, and the clock is the factory's rather than the
 * server's. They are read from `/api/health`, not written here, so a pill that
 * says "read-only" is reporting the live connection.
 */
export function Header({ health }: { health: Health | null }) {
  const degraded = health?.agent.understanding === "rules";

  return (
    <header className="bg-slate-900 text-white">
      <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-6 gap-y-3 px-5 py-4">
        <div className="mr-auto">
          <h1 className="text-[17px] font-semibold tracking-tight">
            Smart CNC Factory <span className="text-sky-400">MES Copilot</span>
          </h1>
          <p className="mt-0.5 text-[12px] text-slate-400">
            Natural language → controlled MES tools → deterministic calculation → validated answer
          </p>
        </div>

        {health ? (
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`pill ${
                degraded
                  ? "bg-amber-400/10 text-amber-200 ring-amber-300/30"
                  : "bg-sky-400/10 text-sky-200 ring-sky-300/30"
              }`}
              title={
                degraded
                  ? "No model is reachable. Understanding falls back to deterministic rules; the factory numbers are unaffected."
                  : "The language model runs inside this environment. Factory data never leaves it."
              }
            >
              <Dot on={!degraded} />
              {degraded ? "model unavailable — rules" : "local model"}
            </span>

            <span
              className="pill bg-emerald-400/10 text-emerald-200 ring-emerald-300/30"
              title={`Tools connect as ${health.database.user}: SELECT only.`}
            >
              <Dot on={health.database.read_only} />
              DB read-only
            </span>

            <span className="pill bg-white/5 text-slate-300 ring-white/10">
              {health.tools.implemented}/{health.tools.total} MES tools
            </span>

            <span className="pill bg-white/5 text-slate-300 ring-white/10 tabular">
              {factoryDate(health.factory.today)} {factoryTime(health.factory.now)}{" "}
              <span className="text-slate-500">{health.factory.timezone}</span>
            </span>
          </div>
        ) : (
          <span className="pill bg-red-400/10 text-red-200 ring-red-300/30">
            <Dot on={false} />
            backend unreachable
          </span>
        )}
      </div>
    </header>
  );
}

function Dot({ on }: { on: boolean }) {
  return (
    <span
      aria-hidden
      className={`h-1.5 w-1.5 rounded-full ${on ? "bg-current" : "bg-current/40"}`}
    />
  );
}
