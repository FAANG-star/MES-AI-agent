import { expect, test } from "@playwright/test";

import { API, horizontalOverflow, watchForErrors } from "./helpers";

/**
 * The page before anyone asks anything: it must already be telling the truth
 * about the factory and about itself.
 */
test.describe("the factory page", () => {
  test("shows the five machines as the MES reports them", async ({ page, request }) => {
    const errors = watchForErrors(page);
    const machines = (await (await request.get(`${API}/api/machines`)).json()).data.machines;

    await page.goto("/");
    for (const machine of machines) {
      await expect(page.getByText(machine.machine_id, { exact: true }).first()).toBeVisible();
    }

    // CNC-02's vibration sensor is offline in the seeded factory: "—", never 0.
    const cnc02 = page.locator("li", { hasText: "CNC-02" }).first();
    await expect(cnc02).toContainText("—");

    expect(errors).toEqual([]);
  });

  test("reports the live system state in the top bar", async ({ page, request }) => {
    const health = await (await request.get(`${API}/api/health`)).json();
    await page.goto("/");

    const header = page.locator("header");
    await expect(header).toContainText(health.agent.understanding === "llm" ? "Local model" : "Rules only");
    await expect(header).toContainText("Read-only MES");
    await expect(header).toContainText(health.factory.timezone.split("/").pop());
  });

  for (const width of [1440, 390]) {
    test(`fits a ${width}px screen without scrolling sideways`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/");
      expect(await horizontalOverflow(page)).toBe(0);
    });
  }
});
