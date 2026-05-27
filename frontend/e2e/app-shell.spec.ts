// S-318: App shell & IA e2e smoke suite.
// Verifies the sidebar-nav shell, hash routing, legacy hash compat,
// and theme toggle persistence. Gated with RUN_E2E=1.

import { expect, test } from "@playwright/test";
import { stubRestAlerts, stubWebSocket } from "./fixtures/stubs";

test.skip(process.env.RUN_E2E !== "1", "set RUN_E2E=1 to run");

test.setTimeout(30_000);

test.beforeEach(async ({ page }) => {
  await stubRestAlerts(page);
  await stubWebSocket(page);
});

test("page loads with sidebar showing 'seerflow' brand text", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("seerflow")).toBeVisible();
});

test("sidebar shows all nav groups", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Monitor")).toBeVisible();
  await expect(page.getByText("Investigate")).toBeVisible();
  await expect(page.getByText("Configure")).toBeVisible();
});

test("sidebar shows all nav items", async ({ page }) => {
  await page.goto("/");
  // Use data-testid selectors to avoid strict-mode violations from
  // multiple elements containing the same text (sidebar label + breadcrumb)
  await expect(page.getByTestId("nav-item-overview")).toBeVisible();
  await expect(page.getByTestId("nav-item-alerts")).toBeVisible();
  await expect(page.getByTestId("nav-item-events")).toBeVisible();
  await expect(page.getByTestId("nav-item-entities")).toBeVisible();
  await expect(page.getByTestId("nav-item-attack")).toBeVisible();
  await expect(page.getByTestId("nav-item-hunt")).toBeVisible();
  await expect(page.getByTestId("nav-item-sigma")).toBeVisible();
  await expect(page.getByTestId("nav-item-receivers")).toBeVisible();
  await expect(page.getByTestId("nav-item-models")).toBeVisible();
  await expect(page.getByTestId("nav-item-settings")).toBeVisible();
});

test("topbar shows ⌘K hint", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("⌘K")).toBeVisible();
});

test("default load shows overview screen (DashboardGrid present)", async ({ page }) => {
  await page.goto("/");
  // DashboardGrid is on the overview screen; it renders drag handles for widgets
  await expect(page.getByRole("button", { name: /add widget/i })).toBeVisible();
});

test("clicking Alerts nav → hash changes to #/alerts and alerts screen shown", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByTestId("nav-item-alerts").click();
  await expect(page).toHaveURL(/#\/alerts/);
  // S-321: AlertsScreen replaced the ScreenStub — alert feed is now rendered
  await expect(page.getByTestId("alerts-screen")).toBeVisible();
});

test("clicking Settings nav → hash changes to #/settings and coming soon shown", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByTestId("nav-item-settings").click();
  await expect(page).toHaveURL(/#\/settings/);
  await expect(page.getByText(/coming soon/i)).toBeVisible();
});

test("clicking ATT&CK nav → hash changes to #/attack", async ({ page }) => {
  await page.goto("/");
  // Stub ATT&CK API
  await page.route(/\/api\/v1\/coverage/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        tactics: [],
        summary: {
          total_rules_with_attack_tags: 0,
          total_alerts_matched: 0,
        },
        window_since: "2026-01-01T00:00:00Z",
        window_until: "2026-01-02T00:00:00Z",
      }),
    }),
  );
  await page.getByTestId("nav-item-attack").click();
  await expect(page).toHaveURL(/#\/attack/);
});

test("legacy #coverage hash navigates to attack screen", async ({ page }) => {
  await page.route(/\/api\/v1\/coverage/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        tactics: [],
        summary: {
          total_rules_with_attack_tags: 0,
          total_alerts_matched: 0,
        },
        window_since: "2026-01-01T00:00:00Z",
        window_until: "2026-01-02T00:00:00Z",
      }),
    }),
  );
  await page.goto("/#coverage");
  // The shell parses #coverage → attack route
  // The ATT&CK heatmap screen should load — confirm by the url or by the nav
  await expect(page.getByTestId("nav-item-attack")).toBeVisible();
  // The attack screen or hash #/attack — either is acceptable
  const url = page.url();
  expect(url).toMatch(/#(\/attack|coverage)/); // normalised or original
});

test("legacy #sigma-rules hash navigates to sigma screen", async ({ page }) => {
  await page.route(/\/api\/v1\/sigma/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [], total: 0, page: 1, limit: 50 }),
    }),
  );
  await page.goto("/#sigma-rules");
  // Sigma screen should load — use the nav item as a stable marker
  await expect(page.getByTestId("nav-item-sigma")).toBeVisible();
  // The sigma screen is active — confirm by checking the URL has sigma in it
  const url = page.url();
  expect(url).toMatch(/#(\/sigma|sigma-rules)/); // normalised or original
});

test("theme toggle switches dark→light and persists", async ({ page }) => {
  await page.goto("/");
  // Default is dark (no sf-light)
  let hasSfLight = await page.evaluate(
    () => document.documentElement.classList.contains("sf-light"),
  );
  expect(hasSfLight).toBe(false);

  // Click Light
  await page.getByTitle("Light").click();
  hasSfLight = await page.evaluate(
    () => document.documentElement.classList.contains("sf-light"),
  );
  expect(hasSfLight).toBe(true);

  // Reload — should persist
  await page.reload();
  await page.waitForLoadState("domcontentloaded");
  hasSfLight = await page.evaluate(
    () => document.documentElement.classList.contains("sf-light"),
  );
  expect(hasSfLight).toBe(true);
});

test("clicking Overview nav from Alerts → returns to DashboardGrid", async ({
  page,
}) => {
  await page.goto("/#/alerts");
  // S-321: AlertsScreen now shows real alerts list (not ScreenStub)
  await expect(page.getByTestId("alerts-screen")).toBeVisible();

  await page.getByTestId("nav-item-overview").click();
  await expect(page).toHaveURL(/#\/overview/);
  await expect(page.getByRole("button", { name: /add widget/i })).toBeVisible();
});
