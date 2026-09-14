import { expect, test } from "@playwright/test";

/**
 * The two viewer preferences. Both are per browser, both must survive a
 * reload, and neither may change a factory answer.
 */
test.describe("viewer preferences", () => {
  test("a chosen theme wins over the system and survives a reload", async ({ browser }) => {
    const context = await browser.newContext({ colorScheme: "dark" });
    const page = await context.newPage();
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

    await page.getByRole("radio", { name: "Light" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

    await page.getByRole("radio", { name: "Match system" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await context.close();
  });

  test("a viewer in another zone sees both clocks and can change theirs", async ({ browser }) => {
    const context = await browser.newContext({ timezoneId: "America/New_York" });
    const page = await context.newPage();
    await page.goto("/");

    const header = page.locator("header");
    await expect(header).toContainText("New York");
    await expect(header).toContainText("Factory");

    await page.getByRole("button", { name: /Change the time zone/i }).click();
    await page.getByPlaceholder(/Search a city/).fill("shanghai");
    await page.getByRole("option", { name: /Asia\/Shanghai/ }).click();
    await expect(header).toContainText("Shanghai");

    await page.reload();
    await expect(header).toContainText("Shanghai");
    await context.close();
  });
});
