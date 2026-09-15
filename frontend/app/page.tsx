import { Copilot } from "@/components/Copilot";
import { MachineStrip } from "@/components/MachineStrip";
import { TimeProvider } from "@/components/TimeProvider";
import { TopBar } from "@/components/TopBar";
import { getFactory, getHealth, getMaintenance } from "@/lib/server";

// Live factory state. Rendering this at build time would ship a photograph of
// a machine hall and call it a status board.
export const dynamic = "force-dynamic";

export default async function Page() {
  const [health, factory, maintenance] = await Promise.all([
    getHealth(),
    getFactory(),
    getMaintenance(),
  ]);

  return (
    <TimeProvider factoryZone={health?.factory.timezone ?? null} serverNow={health?.factory.now ?? null}>
      <TopBar health={health} />

      <main className="mx-auto max-w-[1200px] px-6 pb-16 pt-6">
        <MachineStrip
          machines={factory.machines}
          thresholds={factory.thresholds}
          maintenance={maintenance}
        />

        {!health && (
          <p className="mt-6 rounded-xl border border-bad/30 bg-bad/[0.06] px-4 py-3 text-[13px] text-fg-2">
            The backend at <code className="font-mono">{process.env.MES_API_URL ?? "http://localhost:8000"}</code>{" "}
            is not answering, so no question can be asked. Start it with{" "}
            <code className="font-mono">make up</code>.
          </p>
        )}

        <div className="mt-8">
          <Copilot />
        </div>
      </main>

      <footer className="border-t border-line">
        <p className="mx-auto max-w-[1200px] px-6 py-5 text-[12px] leading-relaxed text-fg-3">
          The language model chooses which question is being asked and how to phrase the result. Every
          figure comes from a deterministic function over the MES and is checked against the retrieved
          data before it is shown.
        </p>
      </footer>
    </TimeProvider>
  );
}
