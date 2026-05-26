// S-317: theme toggle e2e — dark default, .sf-light toggle, persistence across reload.
// Gated with RUN_E2E=1 (same pattern as other e2e specs in this repo).

import { expect, test } from "@playwright/test";
import { stubRestAlerts, stubWebSocket } from "./fixtures/stubs";

test.skip(process.env.RUN_E2E !== "1", "set RUN_E2E=1 to run");

test.setTimeout(30_000);

test.beforeEach(async ({ page }) => {
  // Clear localStorage so we start from clean state (dark default)
  await page.addInitScript(() => {
    localStorage.removeItem("seerflow-theme");
    // Also remove old key
    localStorage.removeItem("seerflow.theme");
  });
  await stubRestAlerts(page);
  await stubWebSocket(page);
  await page.goto("/");
});

test("page loads with dark theme by default (no sf-light class)", async ({ page }) => {
  const hasSfLight = await page.evaluate(
    () => document.documentElement.classList.contains("sf-light"),
  );
  expect(hasSfLight).toBe(false);
});

test("clicking Light button adds sf-light class and persists to localStorage", async ({
  page,
}) => {
  // Find and click the Light button in the ThemeToggle
  const lightBtn = page.getByTitle("Light");
  await lightBtn.click();

  const hasSfLight = await page.evaluate(
    () => document.documentElement.classList.contains("sf-light"),
  );
  expect(hasSfLight).toBe(true);

  const storedTheme = await page.evaluate(
    () => localStorage.getItem("seerflow-theme"),
  );
  expect(storedTheme).toBe("light");
});

test("light theme persists across page reload", async ({ page }) => {
  // Switch to light
  await page.getByTitle("Light").click();

  // Reload without clearing localStorage
  await page.reload();
  await page.waitForLoadState("domcontentloaded");

  const hasSfLight = await page.evaluate(
    () => document.documentElement.classList.contains("sf-light"),
  );
  expect(hasSfLight).toBe(true);
});

test("clicking Dark button removes sf-light class", async ({ page }) => {
  // Start in light mode
  await page.addInitScript(() => {
    localStorage.setItem("seerflow-theme", "light");
  });
  await page.reload();
  await page.waitForLoadState("domcontentloaded");

  const darkBtn = page.getByTitle("Dark");
  await darkBtn.click();

  const hasSfLight = await page.evaluate(
    () => document.documentElement.classList.contains("sf-light"),
  );
  expect(hasSfLight).toBe(false);

  const storedTheme = await page.evaluate(
    () => localStorage.getItem("seerflow-theme"),
  );
  expect(storedTheme).toBe("dark");
});
