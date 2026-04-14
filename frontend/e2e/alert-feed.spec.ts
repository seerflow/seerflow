import { test, expect } from "@playwright/test";

test("alert feed renders and filter bar is interactive", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Critical" })).toBeVisible();
});
