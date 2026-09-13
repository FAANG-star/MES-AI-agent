import { describeSource, sourceLabel } from "@/lib/format";
import type { SourceRef } from "@/lib/types";

import { Eyebrow } from "./ui";

/**
 * Data Used — acceptance criterion 5.
 *
 * Assembled by the backend from what each tool reported reading. The model
 * does not write this list and cannot, which is what makes it worth showing:
 * if a table is here, a query read it.
 */
export function Sources({ sources }: { sources: SourceRef[] }) {
  if (sources.length === 0) return null;

  return (
    <aside className="panel rise p-5">
      <div className="flex items-baseline justify-between gap-3">
        <Eyebrow>Data used</Eyebrow>
        <span className="font-mono text-[11px] text-fg-3">reported by the tools</span>
      </div>

      <ul className="mt-4 divide-y divide-line">
        {sources.map((source) => (
          <li key={source.table} className="py-2.5 first:pt-0 last:pb-0">
            <div className="flex items-baseline justify-between gap-3">
              <span className="inline-flex items-baseline gap-2 text-[13px] text-fg">
                <svg viewBox="0 0 12 12" className="h-3 w-3 shrink-0 translate-y-[1px] text-ok" aria-hidden>
                  <path d="m2.5 6.2 2.3 2.3 4.7-5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                {sourceLabel(source.table)}
              </span>
              <code className="truncate font-mono text-[11px] text-fg-3">{source.table}</code>
            </div>
            <p className="mt-0.5 pl-5 font-mono text-[11px] text-fg-3 tabular" title={source.fields.join(", ")}>
              {describeSource(source)}
            </p>
          </li>
        ))}
      </ul>
    </aside>
  );
}
