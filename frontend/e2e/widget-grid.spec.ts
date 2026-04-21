// AC: S-062C widget-grid smoke. Gated with RUN_E2E=1 (matches
// e2e/alert-feed/disconnect-banner.spec.ts pattern). Exercises the
// widget grid end-to-end: add, remove, reset, empty-state, persistence.
//
// Playwright creates a fresh browser context per test, so localStorage
// starts empty and the layout store rehydrates from DEFAULT_WIDGETS
// (alertFeed, anomalyTimeline, entityExplorer, eventStream) on each
// `page.goto("/")`. The stubs (REST + WS) survive reload because
// `page.route` / `page.routeWebSocket` bindings are attached to the
// browser context, not to the document.
//
// Remove-button clicks go through `locator.dispatchEvent("click")`
// rather than `.click()`. The `×` button lives inside the
// `.widget-drag-handle` div, which react-grid-layout registers as a
// draggable surface via react-draggable's `onMouseDown` listener.
// A real Playwright `.click()` (pointerdown → pointerup at the same
// coords) can land in the drag pipeline instead of React's synthetic
// `onClick` when the handler runs synchronously between the events,
// so the remove never fires. Synthetic `click` dispatch bypasses the
// pointer chain entirely and fires the React onClick directly,
// matching keyboard-Enter activation semantics.

import { expect, test } from "@playwright/test";
import { stubRestAlerts, stubWebSocket } from "./fixtures/stubs";

test.skip(process.env.RUN_E2E !== "1", "set RUN_E2E=1 to run");

test.setTimeout(30_000);

test.beforeEach(async ({ page }) => {
  await stubRestAlerts(page);
  await stubWebSocket(page);
});

test("add widget round-trip: adds, removes, re-appears in menu", async ({ page }) => {
  await page.goto("/");
  // The four default core widgets rehydrate from DEFAULT_WIDGETS on load.
  // Drag-handle aria-labels are unique per widget, so they are the most
  // stable selector for widget presence.
  await expect(page.getByRole("button", { name: "Drag Alert feed" })).toBeVisible();

  // Open the Add widget menu and pick the optional ATT&CK coverage widget.
  await page.getByRole("button", { name: "Add widget" }).click();
  await page.getByRole("menuitem", { name: "ATT&CK coverage" }).click();

  // The widget mounts; its drag handle label is the stable presence marker
  // (two DOM nodes contain the raw text "ATT&CK coverage" — the heatmap
  // header and the frame title — so a plain getByText check would be
  // ambiguous).
  await expect(page.getByRole("button", { name: "Drag ATT&CK coverage" })).toBeVisible();

  // Remove via the frame's × button. See header note about dispatchEvent.
  await page
    .getByRole("button", { name: "Remove ATT&CK coverage" })
    .dispatchEvent("click");
  await expect(page.getByRole("button", { name: "Drag ATT&CK coverage" })).toHaveCount(0);

  // It should re-appear as a selectable item in the Add menu.
  await page.getByRole("button", { name: "Add widget" }).click();
  await expect(page.getByRole("menuitem", { name: "ATT&CK coverage" })).toBeVisible();
});

test("reset layout restores defaults (removes added widgets)", async ({ page }) => {
  await page.goto("/");

  // Add Source health, then reset layout and confirm the dialog.
  await page.getByRole("button", { name: "Add widget" }).click();
  await page.getByRole("menuitem", { name: "Source health" }).click();
  await expect(page.getByRole("button", { name: "Drag Source health" })).toBeVisible();

  await page.getByRole("button", { name: "Reset layout" }).click();
  // The confirm button's accessible name is aria-label="Confirm" (visible
  // text is "Reset"; aria-label wins for the accessible-name computation,
  // see ResetLayoutButton.tsx:37-45).
  await page.getByRole("button", { name: "Confirm" }).click();

  await expect(page.getByRole("button", { name: "Drag Source health" })).toHaveCount(0);
});

test("empty grid shows EmptyGridHint when all widgets removed", async ({ page }) => {
  await page.goto("/");

  // Wait for the default grid to mount before tearing it down.
  await expect(page.getByRole("button", { name: "Drag Alert feed" })).toBeVisible();

  for (const title of ["Alert feed", "Anomaly timeline", "Entity explorer", "Event stream"]) {
    await page
      .getByRole("button", { name: `Remove ${title}` })
      .dispatchEvent("click");
    // Assert unmount before clicking the next remove; react-grid-layout
    // re-renders siblings and their DraggableCore wrappers on each
    // change, so stale handles would otherwise hit the wrong widget.
    await expect(page.getByRole("button", { name: `Drag ${title}` })).toHaveCount(0);
  }

  await expect(page.getByText(/your dashboard is empty/i)).toBeVisible();
});

test("layout persists across reload", async ({ page }) => {
  await page.goto("/");

  await page.getByRole("button", { name: "Add widget" }).click();
  await page.getByRole("menuitem", { name: "Source health" }).click();
  await expect(page.getByRole("button", { name: "Drag Source health" })).toBeVisible();

  // Reload the page. The zustand `persist` middleware serialises the
  // layout to `localStorage["seerflow.dashboard.layout.v1"]`, so the
  // reloaded store must rehydrate with Source health still mounted.
  await page.reload();

  await expect(page.getByRole("button", { name: "Add widget" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Drag Source health" })).toBeVisible();
});
