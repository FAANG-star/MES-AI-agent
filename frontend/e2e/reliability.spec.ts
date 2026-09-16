import { expect, test } from "@playwright/test";

import { ask, askChip, clickAndWait } from "./helpers";

/**
 * The answers the client asked to see that are not answers in the usual sense:
 * a rejection, a refusal and a clarification. Each must look like the system
 * working, not like it failing.
 */
test.describe("reliability", () => {
  test("an off-topic request is rejected without reading the factory (Demo 5)", async ({ page }) => {
    await page.goto("/");
    await askChip(page, "Write me a story.");

    await expect(page.getByText("Outside this assistant’s scope")).toBeVisible();
    await expect(
      page.getByText("This AI assistant is restricted to Smart Factory, CNC, manufacturing and MES-related requests."),
    ).toBeVisible();
    await expect(page.getByText("No tool called · no factory data read")).toBeVisible();
    await expect(page.getByText(/No step ran/)).toBeVisible();
  });

  test("missing data is refused and the field is named (R3)", async ({ page }) => {
    await page.goto("/");
    await askChip(page, "How many B20 parts can we produce tomorrow?");

    // The panel's label, matched exactly: the refusal sentence itself may also
    // contain the phrase ("We cannot calculate the number of B20 parts …"),
    // and a loose match then resolves to two elements.
    await expect(page.getByText("Cannot calculate", { exact: true })).toBeVisible();
    await expect(page.locator("code", { hasText: "parts.cycle_time_min" }).first()).toBeVisible();
    // No figure is produced for a part that cannot be calculated.
    await expect(page.getByText("Estimated B20 capacity")).toHaveCount(0);
  });

  test("an ambiguous question gets one question back, and an option answers it (R2)", async ({
    page,
  }) => {
    await page.goto("/");
    await ask(page, "How many A12?");

    await expect(page.getByText("One detail first")).toBeVisible();
    await expect(page.getByText(/No tool was called/)).toBeVisible();

    await clickAndWait(page, "Maximum production capacity");

    await expect(page.getByText("Estimated A12 capacity")).toBeVisible();
  });
});
