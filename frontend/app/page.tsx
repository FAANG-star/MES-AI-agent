import { Copilot } from "@/components/Copilot";
import { FactoryStatus } from "@/components/FactoryStatus";
import { Header } from "@/components/Header";
import { getFactory, getHealth } from "@/lib/server";

// The factory strip is live state. Rendering it at build time would ship a
// photograph of a machine hall and call it a status board.
export const dynamic = "force-dynamic";

export default async function Page() {
  const [health, factory] = await Promise.all([getHealth(), getFactory()]);

  return (
    <>
      <Header health={health} />

      <main className="mx-auto max-w-[1400px] space-y-4 px-5 py-5">
        <FactoryStatus machines={factory.machines} thresholds={factory.thresholds} />

        {!health && (
          <p className="card p-4 text-[13px] text-slate-600">
            The backend at <span className="mono">{process.env.MES_API_URL ?? "http://localhost:8000"}</span>{" "}
            is not answering, so no question can be asked. Start it with{" "}
            <span className="mono">make up</span>.
          </p>
        )}

        <Copilot />

        <footer className="pb-6 pt-2 text-center text-[11px] leading-relaxed text-slate-400">
          The language model chooses which question is being asked and how to phrase the result. Every
          figure comes from a deterministic function over the MES, and is checked against the
          retrieved data before it is shown.
        </footer>
      </main>
    </>
  );
}
