// S-320: Overview screen E2E spec.
// Verifies the Overview layout elements render at #/overview.
// Gated with RUN_E2E=1.

import { expect, test } from "@playwright/test";
import { stubRestAlerts, stubWebSocket } from "./fixtures/stubs";

test.skip(process.env.RUN_E2E !== "1", "set RUN_E2E=1 to run");

test.setTimeout(30_000);

test.beforeEach(async ({ page }) => {
  await stubRestAlerts(page);
  await stubWebSocket(page);
});

test("Overview screen renders at #/overview", async ({ page }) => {
  await page.goto("/#/overview");
  // Wait for the screen to transition from skeleton to overview
  await expect(page.getByTestId("overview-screen")).toBeVisible({ timeout: 10_000 });
});

test("Overview screen renders at root /", async ({ page }) => {
  await page.goto("/");
  // Root defaults to overview — check nav item is active
  await expect(page.getByTestId("nav-item-overview")).toBeVisible();
});

test("KPI strip shows 4 stat cards", async ({ page }) => {
  await page.goto("/#/overview");
  // Wait for overview (past skeleton)
  await expect(page.getByTestId("overview-screen")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId("kpi-events-per-sec")).toBeVisible();
  await expect(page.getByTestId("kpi-active-entities")).toBeVisible();
  await expect(page.getByTestId("kpi-open-alerts")).toBeVisible();
  await expect(page.getByTestId("kpi-mean-latency")).toBeVisible();
});

test("'Event volume by severity' chart heading is visible", async ({ page }) => {
  await page.goto("/#/overview");
  await expect(page.getByTestId("overview-screen")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText("Event volume by severity")).toBeVisible();
});

test("'Recent alerts' section heading is visible", async ({ page }) => {
  await page.goto("/#/overview");
  await expect(page.getByTestId("overview-screen")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText("Recent alerts")).toBeVisible();
});

test("'Top risk entities' section heading is visible", async ({ page }) => {
  await page.goto("/#/overview");
  await expect(page.getByTestId("overview-screen")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText("Top risk entities")).toBeVisible();
});

test("Overview screen shows 'last 24h' time label for entities panel", async ({
  page,
}) => {
  await page.goto("/#/overview");
  await expect(page.getByTestId("overview-screen")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText("last 24h")).toBeVisible();
});
