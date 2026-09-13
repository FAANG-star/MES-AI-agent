import { describeSource, sourceLabel } from "@/lib/format";
import type { SourceRef } from "@/lib/types";

/**
 * "Data Used" — acceptance criterion 5, and the panel from the client's mock.
 *
 * The list is assembled by the backend from what each tool reported it read:
 * the table, the columns, the entity ids and the row count. It is not written
 * by the model and cannot be, which is the property that makes it worth
 * showing. If a row is here, a query returned it.
 */
export function DataUsed({ sources }: { sources: SourceRef[] }) {
  if (sources.length === 0) return null;

  return (
    <section className="card" aria-labelledby="data-used">
      <h2 id="data-used" className="card-title flex items-center justify-between">
        <span>Data used</span>
        <span className="font-normal normal-case tracking-normal text-slate-400">
          reported by the tools
        </span>
      </h2>

      <ul className="divide-y divide-slate-200/70">
        {sources.map((source) => (
          <li key={source.table} className="px-4 py-2.5">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-[13px] text-slate-800">
                <span className="mr-1.5 text-emerald-600" aria-hidden>
                  ✓
                </span>
                {sourceLabel(source.table)}
              </span>
              <span className="mono shrink-0 text-slate-400">{source.table}</span>
            </div>

            <p className="mt-0.5 pl-[18px] text-[11px] text-slate-500">
              {describeSource(source)}
            </p>

            {source.fields.length > 0 && (
              <p className="mono mt-0.5 pl-[18px] text-[11px] leading-relaxed text-slate-400">
                {source.fields.join(" · ")}
              </p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
