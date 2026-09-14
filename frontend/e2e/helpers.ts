import { expect, type Page } from "@playwright/test";

export const API = process.env.E2E_API_URL ?? "http://localhost:8000";

/** Two model calls on CPU, with room to spare. */
const RUN_TIMEOUT = 5 * 60_000;

/**
 * Wait for a run by its stream, not by the look of the page.
 *
 * The first version waited for the question box to be disabled and then
 * enabled again. A rejected request settles in milliseconds — faster than the
 * box is ever observed disabled — so that wait sat out its full timeout. The
 * stream closing is the one signal every run produces, fast or slow.
 */
async function runFinishes(page: Page, trigger: () => Promise<void>) {
  const stream = page.waitForResponse((r) => r.url().includes("/api/mes/ask/stream"), {
    timeout: RUN_TIMEOUT,
  });
  await trigger();
  await (await stream).finished();
  await expect(page.locator("#question")).toBeEnabled();
}

/** Ask through the question box and wait for the run to finish. */
export async function ask(page: Page, question: string) {
  const box = page.locator("#question");
  await box.fill(question);
  await runFinishes(page, () => box.press("Enter"));
}

/** Click an example chip and wait for its run. */
export async function askChip(page: Page, text: string) {
  await runFinishes(page, () =>
    page.getByRole("button", { name: text, exact: false }).first().click(),
  );
}

/** Click something that starts a run (a clarification option) and wait for it. */
export async function clickAndWait(page: Page, name: string) {
  await runFinishes(page, () => page.getByRole("button", { name }).click());
}

/** Collect anything the browser reports as broken. */
export function watchForErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`console: ${message.text()}`);
  });
  page.on("response", (response) => {
    if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`);
  });
  return errors;
}

export async function horizontalOverflow(page: Page): Promise<number> {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
}
