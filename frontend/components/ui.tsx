/**
 * The handful of primitives every panel shares. Kept deliberately small: a
 * design with few parts stays consistent without having to be policed.
 */

export function Eyebrow({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <p className={`eyebrow ${className}`}>{children}</p>;
}

export type Tone = "ok" | "warn" | "bad" | "muted" | "accent";

const DOT: Record<Tone, string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  bad: "bg-bad",
  muted: "bg-fg-3",
  accent: "bg-accent",
};

const TEXT: Record<Tone, string> = {
  ok: "text-ok",
  warn: "text-warn",
  bad: "text-bad",
  muted: "text-fg-3",
  accent: "text-accent",
};

export function Dot({ tone, pulse = false }: { tone: Tone; pulse?: boolean }) {
  return (
    <span aria-hidden className="relative inline-flex h-1.5 w-1.5 shrink-0">
      {pulse && (
        <span className={`absolute inset-0 animate-ping rounded-full opacity-60 ${DOT[tone]}`} />
      )}
      <span className={`relative h-1.5 w-1.5 rounded-full ${DOT[tone]}`} />
    </span>
  );
}

/** A small labelled fact: "● Validated against MES data". */
export function Badge({
  tone,
  children,
  title,
}: {
  tone: Tone;
  children: React.ReactNode;
  title?: string;
}) {
  return (
    <span
      title={title}
      className="inline-flex items-center gap-2 rounded-full border border-line bg-tint/[0.02] px-2.5 py-1 text-[12px] text-fg-2"
    >
      <Dot tone={tone} />
      {children}
    </span>
  );
}

export function toneText(tone: Tone): string {
  return TEXT[tone];
}

/** A titled region separated by a hairline — the page's only container. */
export function Section({
  title,
  aside,
  children,
  className = "",
}: {
  title: string;
  aside?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`rise border-t border-line pt-5 ${className}`}>
      <div className="mb-4 flex items-baseline justify-between gap-4">
        <h3 className="text-[13px] font-medium text-fg">{title}</h3>
        {aside && <span className="eyebrow hidden text-right sm:inline">{aside}</span>}
      </div>
      {children}
    </section>
  );
}
