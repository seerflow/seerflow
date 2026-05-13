import { test, expect } from "@playwright/test";

const GATED = !process.env.PLAYWRIGHT;

test.describe("feedback flow", () => {
  test.skip(GATED, "PLAYWRIGHT env flag not set (Sprint 11 infra gate)");

  test("inline TP click shows toast and appears in history", async ({ page }) => {
    await page.goto("/");
    const row = page.getByRole("button", { name: /alert / }).first();
    await row.getByRole("button", { name: /mark true positive/i }).click();
    await expect(page.getByText(/marked as true positive/i)).toBeVisible();
    await row.click();
    const historyRow = page.locator("[data-testid=feedback-history-row]").first();
    await expect(historyRow).toContainText(/tp/i);
    await expect(historyRow).toContainText(/dashboard/i);
  });
});
