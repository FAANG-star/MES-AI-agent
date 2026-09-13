/**
 * Light and dark, and who decides.
 *
 * By default the operating system does: a manager who runs their laptop dark
 * gets a dark copilot. Choosing a theme overrides that for this browser. The
 * choice lives in localStorage and is applied by an inline script before the
 * first paint, so a dark page never flashes white on load (or the reverse).
 */

export type ThemeChoice = "system" | "light" | "dark";
export type Theme = "light" | "dark";

export const THEME_STORAGE_KEY = "mes-copilot-theme";
export const THEME_EVENT = "mes-copilot-theme";

export function parseChoice(stored: string | null | undefined): ThemeChoice {
  return stored === "light" || stored === "dark" ? stored : "system";
}

export function resolveTheme(choice: ThemeChoice, systemPrefersDark: boolean): Theme {
  if (choice === "system") return systemPrefersDark ? "dark" : "light";
  return choice;
}

/**
 * Runs in <head>, before React and before paint. Kept dependency-free and
 * wrapped in try: private browsing can refuse localStorage, and a page that
 * fails to pick a theme must still render — in light, the CSS default.
 */
export const THEME_SCRIPT = `(function(){try{var c=localStorage.getItem(${JSON.stringify(
  THEME_STORAGE_KEY,
)});var d=window.matchMedia("(prefers-color-scheme: dark)").matches;document.documentElement.dataset.theme=(c==="light"||c==="dark")?c:(d?"dark":"light");}catch(e){}})();`;
