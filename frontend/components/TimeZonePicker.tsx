"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { allZones, deviceZone, relativeToFactory, wallClock, zoneCity } from "@/lib/timezone";

import { useTime } from "./TimeProvider";

const SUGGESTED = ["Asia/Shanghai", "Asia/Tokyo", "Asia/Singapore", "Asia/Kolkata", "Europe/Berlin", "Europe/London", "America/New_York", "UTC"];
const LIMIT = 80;

/**
 * The factory clock and the viewer's clock, and the control that changes the
 * viewer's.
 *
 * Only the viewer's zone can be changed here. The factory's zone is a
 * deployment setting (`make factory-timezone`) because it changes what "today"
 * means for every question anyone asks; letting one viewer move it from a web
 * page would change everyone else's answers under them.
 */
export function TimeZonePicker() {
  const { factoryZone, viewerZone, automatic, setViewerZone, now, factoryClock, viewerClock } = useTime();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const root = useRef<HTMLDivElement>(null);
  const search = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    search.current?.focus();
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    const onClick = (event: MouseEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onClick);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  const zones = useMemo(() => allZones(), []);
  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase().replaceAll(" ", "_");
    const list = needle
      ? zones.filter((zone) => zone.toLowerCase().includes(needle))
      : [...new Set([...SUGGESTED.filter((z) => zones.includes(z) || z === "UTC"), ...zones])];
    return list.slice(0, LIMIT);
  }, [query, zones]);

  if (!factoryZone || !factoryClock) return null;

  const differs = viewerZone !== null && viewerZone !== factoryZone;
  const choose = (zone: string | null) => {
    setViewerZone(zone);
    setOpen(false);
    setQuery("");
  };

  return (
    <div ref={root} className="relative flex items-center gap-4">
      {/* The factory's clock is always shown: it is the one answers are about. */}
      <span
        className={`items-center gap-1.5 whitespace-nowrap font-mono tabular text-fg-2 ${differs ? "hidden md:inline-flex" : "hidden"}`}
        title={`Factory time · ${factoryZone} (${factoryClock.offset})`}
      >
        <span className="font-sans text-fg-3">Factory</span>
        <span className="text-fg">{factoryClock.time}</span>
        <span className="text-fg-3">{zoneCity(factoryZone)}</span>
      </span>

      <button
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        // Without a label the button announced itself as "You 13:50 New York" —
        // a clock, not a control. Found by the end-to-end suite, which could not
        // find the button by what it does.
        aria-label={`Time zone: ${zoneCity(viewerZone ?? factoryZone)}. Change the time zone times are shown in`}
        title="Change the time zone times are shown in"
        className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-line px-2.5 py-1 font-mono tabular text-fg-2 transition-colors hover:border-fg-3 hover:text-fg"
      >
        <GlobeIcon />
        {differs && <span className="hidden font-sans text-fg-3 sm:inline">You</span>}
        <span className="text-fg">{(viewerClock ?? factoryClock).time}</span>
        <span className="hidden text-fg-3 sm:inline">{zoneCity(viewerZone ?? factoryZone)}</span>
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Time zone"
          className="rise fixed inset-x-4 top-16 z-50 overflow-hidden rounded-2xl border border-line-strong bg-raised shadow-[var(--composer-shadow)] sm:absolute sm:inset-x-auto sm:right-0 sm:top-[calc(100%+10px)] sm:w-[360px]"
        >
          <div className="border-b border-line p-4">
            <p className="eyebrow">Show times in</p>
            <input
              ref={search}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search a city or zone — e.g. Shanghai"
              className="mt-2.5 h-9 w-full rounded-lg border border-line-strong bg-canvas px-3 font-sans text-[13px] text-fg outline-none placeholder:text-fg-3 focus:border-accent/60"
            />
            <div className="mt-3 flex flex-wrap gap-1.5 font-sans">
              <Quick active={automatic} onClick={() => choose(null)}>
                Device · {zoneCity(deviceZone())}
              </Quick>
              <Quick active={!automatic && viewerZone === factoryZone} onClick={() => choose(factoryZone)}>
                Factory · {zoneCity(factoryZone)}
              </Quick>
            </div>
          </div>

          <ul className="max-h-72 overflow-y-auto py-1.5" role="listbox" aria-label="Time zones">
            {matches.length === 0 && (
              <li className="px-4 py-3 font-sans text-[13px] text-fg-3">No zone matches “{query}”.</li>
            )}
            {matches.map((zone) => {
              const clock = wallClock(now, zone);
              const selected = zone === viewerZone && !automatic;
              return (
                <li key={zone}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={selected}
                    onClick={() => choose(zone)}
                    className={`flex w-full items-center gap-3 px-4 py-2 text-left transition-colors hover:bg-tint/[0.04] ${
                      selected ? "bg-accent-soft" : ""
                    }`}
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-sans text-[13px] text-fg">{zoneCity(zone)}</span>
                      <span className="block truncate font-mono text-[11px] text-fg-3">{zone}</span>
                    </span>
                    <span className="text-right font-mono text-[12px] tabular">
                      <span className="block text-fg">{clock.time}</span>
                      <span className="block text-[10px] text-fg-3">{clock.offset}</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>

          <div className="border-t border-line bg-canvas/60 px-4 py-3 font-sans text-[12px] leading-relaxed text-fg-3">
            {viewerZone && <p className="text-fg-2">You are {relativeToFactory(now, viewerZone, factoryZone)}.</p>}
            <p className="mt-1">
              This changes how times are shown. <span className="text-fg-2">&ldquo;Today&rdquo; in an answer is always the
              factory&rsquo;s day</span> ({factoryZone}), because that is how its shifts and records are dated.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function Quick({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-full border px-2.5 py-1 text-[12px] transition-colors ${
        active ? "border-accent/50 bg-accent-soft text-fg" : "border-line-strong text-fg-2 hover:border-fg-3 hover:text-fg"
      }`}
    >
      {children}
    </button>
  );
}

function GlobeIcon() {
  return (
    <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 text-fg-3" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden>
      <circle cx="8" cy="8" r="6" />
      <path d="M2 8h12M8 2c1.8 1.7 2.7 3.7 2.7 6S9.8 12.3 8 14c-1.8-1.7-2.7-3.7-2.7-6S6.2 3.7 8 2Z" />
    </svg>
  );
}
