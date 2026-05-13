import { test, expect } from "@playwright/test";

test.describe("entity explorer", () => {
  test.skip(!process.env.RUN_E2E, "RUN_E2E=1 required");

  test("search → detail → back → dashboard", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("combobox", { name: /search entities/i })).toBeVisible();

    // Exercise search. The test fixture backend is expected to have at least
    // one entity seeded; fall back to a UUID lookup otherwise.
    await page.getByRole("combobox", { name: /search entities/i }).fill("test");
    const option = page.getByRole("option").first();
    await option.waitFor({ state: "visible", timeout: 3000 }).catch(async () => {
      // Fallback: use a UUID-shaped query to force the entity path
      await page.getByRole("combobox", { name: /search entities/i }).fill("11111111-2222-3333-4444-555555555555");
    });
    await page.keyboard.press("Enter");

    // Detail renders
    await expect(page.getByRole("region", { name: /entity detail/i })).toBeVisible();

    // Browser Back restores dashboard
    await page.goBack();
    await expect(page.getByRole("region", { name: /entity detail/i })).toBeHidden();
    await expect(page.getByRole("combobox", { name: /search entities/i })).toBeVisible();
  });
});
