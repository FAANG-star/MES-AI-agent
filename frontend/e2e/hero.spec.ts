import { expect, test } from "@playwright/test";

import { API, askChip, watchForErrors } from "./helpers";

/**
 * Demo 4 — the hero: Question → Plan → MES tools → Calculation → Verification →
 * Explained answer. Every claim on screen is checked against the backend's own
 * tool, called directly, rather than against itself.
 */
test("the hero question shows the engine's figure, the plan and the sources", async ({
  page,
  request,
}) => {
  const errors = watchForErrors(page);
  const truth = await (
    await request.post(`${API}/api/tools/calculate_production_capacity`, {
      data: { part_id: "A12", time_window: "this_week" },
    })
  ).json();
  const capacity = truth.data.capacity.final_capacity as number;
  const bottleneck = truth.data.constraint.bottleneck?.machine_id as string | undefined;

  await page.goto("/");
  await askChip(page, "How many A12 parts can we produce this week?");

  // The headline is the engine's number, formatted, not re-derived.
  await expect(page.getByText(new Intl.NumberFormat("en-US").format(capacity), { exact: true })).toBeVisible();
  await expect(page.getByText("Validated against MES data")).toBeVisible();
  if (bottleneck) {
    await expect(page.getByRole("note", { name: "Bottleneck" })).toContainText(bottleneck);
  }

  // FR-4: eight steps, five of them controlled MES calls.
  await expect(page.getByText("8 steps · 5 MES calls")).toBeVisible();

  // The engine's own working, ending in the final figure.
  await expect(page.getByText("How the number was calculated")).toBeVisible();
  await expect(page.locator("pre")).toContainText(`= ${capacity} parts`);

  // Data Used, as in the client's mock.
  for (const label of ["Machine availability", "Cycle time and routing", "Maintenance schedule", "Material inventory"]) {
    await expect(page.getByText(label, { exact: true })).toBeVisible();
  }

  expect(errors).toEqual([]);
});
