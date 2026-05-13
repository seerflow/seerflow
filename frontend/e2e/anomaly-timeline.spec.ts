import { expect, test } from "@playwright/test";

const RUN_E2E = process.env.RUN_E2E === "1";

test.skip(!RUN_E2E, "E2E infra lands in a later sprint story");

test("anomaly timeline warm-up + range switch", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Anomaly Timeline")).toBeVisible();
  await page.getByRole("button", { name: "24h" }).click();
  await expect(page.getByRole("button", { name: "24h" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

test("threshold line renders on mount", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Anomaly Timeline")).toBeVisible();
  const chartArea = page.locator("[role='img'][aria-label*='Anomaly score chart']");
  await expect(chartArea).toBeVisible();
  const thresholdLine = chartArea.locator("path[stroke-dasharray='4 2']");
  await expect(thresholdLine).toBeVisible();
});

test("alert marker click opens detail panel", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Anomaly Timeline")).toBeVisible();
  const dots = page.locator("[role='img'] circle[fill='var(--color-chart-alert)']");
  const count = await dots.count();
  if (count > 0) {
    await dots.first().click();
    await expect(
      page.locator("text=Alert Details").or(page.locator("[data-testid='alert-detail']")),
    ).toBeVisible({ timeout: 3000 });
  }
});
