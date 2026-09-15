import { expect, test } from "@playwright/test";

import { API, horizontalOverflow, watchForErrors } from "./helpers";

/**
 * Every machine on the strip opens its own record, and the readings stay on
 * the page behind it — the strip is the status board, and the panel is what a
 * reading cannot say.
 */
test.describe("machine detail", () => {
  test("opens the record of every machine the MES reports", async ({ page, request }) => {
    const errors = watchForErrors(page);
    const machines = (await (await request.get(`${API}/api/machines`)).json()).data.machines;

    await page.goto("/");

    for (const machine of machines) {
      await page.getByRole("button", { name: `${machine.machine_id} details` }).click();

      const panel = page.getByRole("dialog", { name: `${machine.machine_id} details` });
      await expect(panel).toBeVisible();
      await expect(panel).toContainText(machine.machine_name);
      await expect(panel).toContainText(machine.machine_type);
      await expect(panel).toContainText(machine.status);

      await page.keyboard.press("Escape");
      await expect(panel).toBeHidden();
    }

    expect(errors).toEqual([]);
  });

  test("names the type in words a factory manager uses", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "CNC-01 details" }).click();

    const panel = page.getByRole("dialog", { name: "CNC-01 details" });
    // A12 runs on lathes; the mills are excluded from an A12 calculation, so
    // the panel has to make the distinction visible.
    await expect(panel).toContainText("CNC lathe");

    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "CNC-04 details" }).click();
    await expect(page.getByRole("dialog", { name: "CNC-04 details" })).toContainText(
      "CNC milling machine",
    );
  });

  test("shows each reading against the factory's limit", async ({ page, request }) => {
    const body = (await (await request.get(`${API}/api/machines`)).json()).data;
    const temperature = body.thresholds.find(
      (t: { rule_key: string }) => t.rule_key === "machine.temperature_c",
    );

    await page.goto("/");
    await page.getByRole("button", { name: "CNC-01 details" }).click();

    const panel = page.getByRole("dialog", { name: "CNC-01 details" });
    // CNC-01 is the seeded temperature breach: 72.5 °C against a 70 °C limit.
    await expect(panel).toContainText(String(temperature.warning_threshold));
    await expect(panel).toContainText("at limit");
  });

  test("lists the maintenance booked against the machine", async ({ page, request }) => {
    const schedule = await (
      await request.post(`${API}/api/tools/get_maintenance_schedule`, {
        data: { machine_id: "CNC-03", time_window: "this_week" },
      })
    ).json();
    const hours = schedule.data.hours_by_machine["CNC-03"];

    await page.goto("/");
    await page.getByRole("button", { name: "CNC-03 details" }).click();

    const panel = page.getByRole("dialog", { name: "CNC-03 details" });
    if (hours) {
      // The same total the capacity engine subtracts, not a sum made on screen.
      await expect(panel).toContainText(`${hours} h scheduled`);
      await expect(panel).toContainText("Preventive");
    } else {
      await expect(panel).toContainText("Nothing scheduled");
    }
    await expect(panel).toContainText(
      schedule.data.machines_under_maintenance_today.includes("CNC-03")
        ? "active today"
        : "nothing active today",
    );
  });

  test("keeps the readings on the page behind the panel", async ({ page }) => {
    await page.goto("/");

    const card = page.locator("li", { hasText: "CNC-01" }).first();
    const readings = await card.innerText();

    await page.getByRole("button", { name: "CNC-01 details" }).click();
    await expect(page.getByRole("dialog", { name: "CNC-01 details" })).toBeVisible();
    // The strip is still rendered, with its numbers, while the panel is open.
    await expect(card).toContainText(readings.split("\n")[0]);
  });

  test("moves between machines with the arrow keys", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "CNC-02 details" }).click();

    await page.keyboard.press("ArrowRight");
    await expect(page.getByRole("dialog", { name: "CNC-03 details" })).toBeVisible();

    await page.keyboard.press("ArrowLeft");
    await expect(page.getByRole("dialog", { name: "CNC-02 details" })).toBeVisible();
  });

  test("fits a phone screen", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await page.getByRole("button", { name: "CNC-03 details" }).click();

    await expect(page.getByRole("dialog", { name: "CNC-03 details" })).toBeVisible();
    expect(await horizontalOverflow(page)).toBe(0);
  });
});
