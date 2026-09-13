import { describe, expect, it } from "vitest";

import { parseChoice, resolveTheme, THEME_SCRIPT, THEME_STORAGE_KEY } from "@/lib/theme";

describe("choosing a theme", () => {
  it("follows the system unless a theme was chosen", () => {
    expect(parseChoice(null)).toBe("system");
    expect(parseChoice("light")).toBe("light");
    expect(parseChoice("dark")).toBe("dark");
  });

  it("treats anything unrecognised in storage as no choice", () => {
    expect(parseChoice("sepia")).toBe("system");
    expect(parseChoice("")).toBe("system");
  });

  it("resolves 'system' from the operating system's preference", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
  });

  it("lets an explicit choice win over the operating system", () => {
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });
});

describe("the before-paint script", () => {
  function run(stored: string | null, prefersDark: boolean, storageThrows = false) {
    const root = { dataset: {} as Record<string, string> };
    const scope = {
      localStorage: {
        getItem: (key: string) => {
          if (storageThrows) throw new Error("denied");
          return key === THEME_STORAGE_KEY ? stored : null;
        },
      },
      window: { matchMedia: () => ({ matches: prefersDark }) },
      document: { documentElement: root },
    };
    new Function("localStorage", "window", "document", THEME_SCRIPT)(
      scope.localStorage,
      scope.window,
      scope.document,
    );
    return root.dataset.theme;
  }

  it("applies a stored choice", () => {
    expect(run("dark", false)).toBe("dark");
    expect(run("light", true)).toBe("light");
  });

  it("falls back to the system preference", () => {
    expect(run(null, true)).toBe("dark");
    expect(run(null, false)).toBe("light");
  });

  it("never throws when storage is refused", () => {
    // Private browsing can deny localStorage. The page must still render, in
    // the CSS default, rather than stop the script and everything after it.
    expect(() => run(null, true, true)).not.toThrow();
  });
});
