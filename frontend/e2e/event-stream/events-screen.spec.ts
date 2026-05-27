/**
 * S-325: Event Stream screen E2E tests.
 *
 * Verifies:
 * - Toolbar elements (live dot, query field, Pause + Export buttons)
 * - Volume strip label
 * - Table column headers
 * - Event row appears after WS push + severity tinting
 * - Inspector panel updates on row click
 */

import { expect, test } from "@playwright/test";
import { stubWebSocket } from "../fixtures/stubs";

test.skip(process.env.RUN_E2E !== "1", "set RUN_E2E=1 to run");

// Helper: stub the events REST warm-up endpoint (returns empty list)
async function stubRestEvents(page: import("@playwright/test").Page): Promise<void> {
  await page.route(/\/api\/v1\/events(\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [], total: 0, page: 1, limit: 100, has_next: false }),
    });
  });
}

// Helper: build a LiveEvent fixture with timestamp_ns as string (wire format)
function makeLiveEvent(i: number, overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    event_id: `e2e-evt-${i}`,
    timestamp_ns: `170000000000000000${i}`,
    observed_ns: `170000000000100000${i}`,
    severity_id: 2,
    severity_text: "INFO",
    source_type: "syslog",
    message: `E2E test event message ${i}`,
    template_id: 1,
    entity_refs: [],
    entity_summary: { hosts: [`e2e-host-${i}`] },
    ...overrides,
  };
}

test("events screen toolbar elements are present", async ({ page }) => {
  await stubRestEvents(page);
  const ws = await stubWebSocket(page);

  await page.goto("/#/events");

  // Live dot / label
  await expect(page.getByTestId("live-label")).toBeVisible();

  // Query field
  await expect(page.getByTestId("query-field")).toBeVisible();
  await expect(page.getByText(/jq · sigma · sql/i)).toBeVisible();

  // Pause button
  await expect(page.getByRole("button", { name: /pause/i })).toBeVisible();

  // Export button
  await expect(page.getByRole("button", { name: /export/i })).toBeVisible();

  // Ensure ws is connected (prevents dangling route warnings)
  ws.close();
});

test("events screen shows volume strip label", async ({ page }) => {
  await stubRestEvents(page);
  const ws = await stubWebSocket(page);

  await page.goto("/#/events");

  await expect(page.getByText(/volume · 60s window/i)).toBeVisible();

  ws.close();
});

test("events screen shows all six column headers", async ({ page }) => {
  await stubRestEvents(page);
  const ws = await stubWebSocket(page);

  await page.goto("/#/events");

  for (const col of ["timestamp", "level", "source", "host", "logger", "message"]) {
    await expect(page.getByText(col, { exact: true })).toBeVisible();
  }

  ws.close();
});

test("events screen shows event row after WS push", async ({ page }) => {
  await stubRestEvents(page);
  const ws = await stubWebSocket(page);

  await page.goto("/#/events");

  // Wait for toolbar to load
  await expect(page.getByTestId("live-label")).toBeVisible();

  // Push a live event over WS
  ws.send({ type: "event", data: makeLiveEvent(1) });

  // Row should appear
  const rows = page.getByRole("button", { name: /event row/i });
  await expect(rows).toHaveCount(1, { timeout: 5000 });

  ws.close();
});

test("events screen shows WARN severity tinted row after WS push", async ({ page }) => {
  await stubRestEvents(page);
  const ws = await stubWebSocket(page);

  await page.goto("/#/events");

  await expect(page.getByTestId("live-label")).toBeVisible();

  // Push a WARN event
  ws.send({
    type: "event",
    data: makeLiveEvent(2, { severity_id: 4, severity_text: "WARN" }),
  });

  const rows = page.getByRole("button", { name: /event row/i });
  await expect(rows).toHaveCount(1, { timeout: 5000 });

  // Row should have data-severity=warn
  await expect(rows.first()).toHaveAttribute("data-severity", "warn");

  ws.close();
});

test("clicking event row updates the inspector panel", async ({ page }) => {
  await stubRestEvents(page);
  const ws = await stubWebSocket(page);

  await page.goto("/#/events");

  await expect(page.getByTestId("live-label")).toBeVisible();

  // Push an ERROR event with a known message
  ws.send({
    type: "event",
    data: makeLiveEvent(3, {
      severity_id: 5,
      severity_text: "ERROR",
      message: "inspector_test_message",
      entity_summary: { hosts: ["inspector-host"] },
    }),
  });

  const rows = page.getByRole("button", { name: /event row/i });
  await expect(rows).toHaveCount(1, { timeout: 5000 });

  // Click the row
  await rows.first().click();

  // Inspector should show the severity badge
  await expect(page.getByTestId("inspector-severity")).toHaveText("ERROR");

  // Inspector should show entity in the entity rows (scoped to inspector-entity-row)
  await expect(page.getByTestId("inspector-entity-row").filter({ hasText: "inspector-host" })).toBeVisible();

  ws.close();
});

test("inspector shows placeholder when no event is selected", async ({ page }) => {
  await stubRestEvents(page);
  const ws = await stubWebSocket(page);

  await page.goto("/#/events");

  await expect(page.getByText(/select an event to inspect/i)).toBeVisible();

  ws.close();
});
