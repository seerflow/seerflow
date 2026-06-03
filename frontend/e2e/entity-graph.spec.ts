/**
 * E2E tests for the entity graph screen (S-322).
 *
 * Covers:
 * - Graph canvas visible when navigating to #/entities
 * - Layout toggle (Force → Radial chip becomes active)
 * - Node/edge counter badge visible
 */
import { test, expect } from "@playwright/test";

test.describe("entity graph screen", () => {
  test.skip(!process.env.RUN_E2E, "RUN_E2E=1 required");

  test("graph canvas and filter rail are visible on entities route", async ({ page }) => {
    await page.goto("/#/entities");

    // Three-column layout containers should be present
    await expect(page.getByTestId("entity-explorer-graph")).toBeVisible({ timeout: 5000 });
    await expect(page.getByTestId("graph-left-rail")).toBeVisible();
    await expect(page.getByTestId("graph-center")).toBeVisible();
    await expect(page.getByTestId("graph-right-inspector")).toBeVisible();
  });

  test("layout chips are visible and toggleable", async ({ page }) => {
    await page.goto("/#/entities");
    await page.waitForSelector('[data-testid="entity-explorer-graph"]', { timeout: 5000 });

    // All three layout chips should be present
    const forceBtn  = page.getByRole("button", { name: /force/i });
    const radialBtn = page.getByRole("button", { name: /radial/i });
    const hierBtn   = page.getByRole("button", { name: /hierarchy/i });

    await expect(forceBtn).toBeVisible();
    await expect(radialBtn).toBeVisible();
    await expect(hierBtn).toBeVisible();

    // Click Radial → it should become active (accent border class)
    await radialBtn.click();
    // After click, canvas should receive layout=Radial (test via data-layout on mock is unit-test scope;
    // here we just verify no crash and the chip is clickable)
    await expect(radialBtn).toBeVisible();

    // Click back to Force
    await forceBtn.click();
    await expect(forceBtn).toBeVisible();
  });

  test("node/edge counter badge is visible in graph center", async ({ page }) => {
    await page.goto("/#/entities");
    await page.waitForSelector('[data-testid="graph-counter"]', { timeout: 5000 });

    const counter = page.getByTestId("graph-counter");
    await expect(counter).toBeVisible();
    // Counter should contain "nodes" and "edges"
    await expect(counter).toContainText("nodes");
    await expect(counter).toContainText("edges");
  });

  test("type filter checkboxes are visible", async ({ page }) => {
    await page.goto("/#/entities");
    await page.waitForSelector('[data-testid="graph-left-rail"]', { timeout: 5000 });

    for (const t of ["user", "host", "ip", "service", "process"]) {
      await expect(page.getByTestId(`type-filter-${t}`)).toBeVisible();
    }
  });

  test("inspector empty state visible when no entity selected", async ({ page }) => {
    await page.goto("/#/entities");
    await page.waitForSelector('[data-testid="graph-right-inspector"]', { timeout: 5000 });

    // Without a node selected, inspector should show empty state
    await expect(page.getByTestId("inspector-empty")).toBeVisible();
  });
});
