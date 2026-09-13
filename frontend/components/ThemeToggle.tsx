"use client";

import { useEffect, useSyncExternalStore } from "react";

import {
  parseChoice,
  resolveTheme,
  THEME_EVENT,
  THEME_STORAGE_KEY,
  type ThemeChoice,
} from "@/lib/theme";

const DARK_QUERY = "(prefers-color-scheme: dark)";

function readChoice(): ThemeChoice {
  try {
    return parseChoice(localStorage.getItem(THEME_STORAGE_KEY));
  } catch {
    return "system";
  }
}

function subscribe(onChange: () => void) {
  window.addEventListener(THEME_EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(THEME_EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

function apply(choice: ThemeChoice) {
  const dark = window.matchMedia(DARK_QUERY).matches;
  document.documentElement.dataset.theme = resolveTheme(choice, dark);
}

const OPTIONS: { value: ThemeChoice; label: string; icon: React.ReactNode }[] = [
  {
    value: "system",
    label: "Match system",
    icon: (
      <>
        <rect x="2.5" y="3.5" width="11" height="7.5" rx="1.2" />
        <path d="M6 13.5h4M8 11v2.5" strokeLinecap="round" />
      </>
    ),
  },
  {
    value: "light",
    label: "Light",
    icon: (
      <>
        <circle cx="8" cy="8" r="2.8" />
        <path
          d="M8 1.8v1.4M8 12.8v1.4M1.8 8h1.4M12.8 8h1.4M3.6 3.6l1 1M11.4 11.4l1 1M3.6 12.4l1-1M11.4 4.6l1-1"
          strokeLinecap="round"
        />
      </>
    ),
  },
  {
    value: "dark",
    label: "Dark",
    icon: <path d="M13 9.6A5.5 5.5 0 0 1 6.4 3a5.5 5.5 0 1 0 6.6 6.6Z" strokeLinejoin="round" />,
  },
];

/**
 * System · Light · Dark. The server cannot know the stored choice, so it
 * renders "system" and the client takes over after hydration — the page
 * itself is already the right colour, set by the script in <head>.
 */
export function ThemeToggle() {
  const choice = useSyncExternalStore(subscribe, readChoice, () => "system" as ThemeChoice);

  // While following the system, follow it live: switching the OS to dark at
  // dusk should switch the copilot too.
  useEffect(() => {
    if (choice !== "system") return;
    const media = window.matchMedia(DARK_QUERY);
    const onChange = () => apply("system");
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [choice]);

  const choose = (next: ThemeChoice) => {
    try {
      if (next === "system") localStorage.removeItem(THEME_STORAGE_KEY);
      else localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // Storage refused (private mode): the theme still applies for this visit.
    }
    apply(next);
    window.dispatchEvent(new Event(THEME_EVENT));
  };

  return (
    <div
      role="radiogroup"
      aria-label="Colour theme"
      className="inline-flex items-center rounded-full border border-line bg-tint/[0.03] p-0.5"
    >
      {OPTIONS.map((option) => {
        const active = choice === option.value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={option.label}
            title={option.label}
            onClick={() => choose(option.value)}
            className={`flex h-6 w-7 items-center justify-center rounded-full transition-colors ${
              active ? "bg-surface text-fg shadow-sm ring-1 ring-line-strong" : "text-fg-3 hover:text-fg"
            }`}
          >
            <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden>
              {option.icon}
            </svg>
          </button>
        );
      })}
    </div>
  );
}
