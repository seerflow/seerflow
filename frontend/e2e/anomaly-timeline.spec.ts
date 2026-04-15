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
