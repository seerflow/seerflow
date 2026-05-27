/**
 * S-321: Alert detail (kill-chain) E2E spec.
 *
 * Verifies the full alert detail flow:
 *   1. Navigate to #/alerts — AlertsScreen renders with alert rows
 *   2. Direct navigation to #/alerts/:id renders the detail view
 *   3. Kill-chain section is visible
 *   4. Header elements (severity badge, score, buttons) are present
 *   5. Right-rail SideBlocks are present
 *   6. Back-navigation returns to alerts list
 */

import { expect, test } from "@playwright/test";
import { stubRestAlerts, stubWebSocket } from "./fixtures/stubs";
import { warmUpAlerts, detailFor } from "./fixtures/alerts";

test.skip(process.env.RUN_E2E !== "1", "set RUN_E2E=1 to run");
test.setTimeout(30_000);

const FIRST_ALERT = warmUpAlerts[0]; // wu-001, "Suspicious PowerShell", severity=6

function stringifyWire(value: unknown): string {
  return JSON.stringify(value, (_k, v) => (typeof v === "bigint" ? v.toString() : v));
}

const KNOWN_ALERT_IDS = new Set(warmUpAlerts.map((a) => a.alert_id));

async function stubAlertDetailRoute(page: import("@playwright/test").Page): Promise<void> {
  await page.route(/\/api\/v1\/alerts\/[^/]+\/feedback/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [], total: 0, page: 1, limit: 10, has_next: false }),
    });
  });

  await page.route(/\/api\/v1\/alerts\/[^/]+$/, async (route) => {
    const id = route.request().url().split("/").pop() ?? "";
    if (!KNOWN_ALERT_IDS.has(id)) {
      await route.fulfill({ status: 404, body: '{"detail":"not found"}' });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: stringifyWire(detailFor(id)),
    });
  });
}

test.beforeEach(async ({ page }) => {
  await stubRestAlerts(page, warmUpAlerts);
  await stubAlertDetailRoute(page);
  await stubWebSocket(page);
});

test("direct navigation to #/alerts/:id renders alert detail screen", async ({ page }) => {
  await page.goto(`/#/alerts/${FIRST_ALERT.alert_id}`);
  await expect(page.getByTestId("alert-detail-screen")).toBeVisible();
});

test("alert detail shows the tactic-chain heading (S-337 reconcile)", async ({ page }) => {
  await page.goto(`/#/alerts/${FIRST_ALERT.alert_id}`);
  // FIRST_ALERT.mitre_tactics = ["execution"] → humanized "Execution" heading.
  await expect(page.getByRole("heading")).toBeVisible();
  await expect(page.getByRole("heading")).toContainText(/Execution/i);
});

test("alert detail shows rule name in the header meta row", async ({ page }) => {
  await page.goto(`/#/alerts/${FIRST_ALERT.alert_id}`);
  await expect(page.getByText(/Suspicious PowerShell/i)).toBeVisible();
});

test("alert detail renders severity badge", async ({ page }) => {
  await page.goto(`/#/alerts/${FIRST_ALERT.alert_id}`);
  // FIRST_ALERT has severity=6 → critical bucket
  await expect(page.getByText(/critical/i).first()).toBeVisible();
});

test("alert detail renders kill-chain timeline list", async ({ page }) => {
  await page.goto(`/#/alerts/${FIRST_ALERT.alert_id}`);
  await expect(page.getByRole("list", { name: /kill.chain/i })).toBeVisible();
});

test("kill-chain shows all 7 stage labels", async ({ page }) => {
  await page.goto(`/#/alerts/${FIRST_ALERT.alert_id}`);
  // Scope to the kill-chain list — "Execution" also appears in the tactic-chain
  // heading and the MITRE rail, so a global getByText would be ambiguous.
  const killChain = page.getByRole("list", { name: /kill.chain/i });
  const stages = [
    "Reconnaissance",
    "Resource Development",
    "Initial Access",
    "Execution",
    "Persistence",
    "Credential Access",
    "Impact",
  ];
  for (const label of stages) {
    await expect(killChain.getByText(label)).toBeVisible();
  }
});

test("alert detail shows Acknowledge button", async ({ page }) => {
  await page.goto(`/#/alerts/${FIRST_ALERT.alert_id}`);
  await expect(page.getByRole("button", { name: /acknowledge/i })).toBeVisible();
});

test("alert detail shows Run playbook button", async ({ page }) => {
  await page.goto(`/#/alerts/${FIRST_ALERT.alert_id}`);
  await expect(page.getByRole("button", { name: /run playbook/i })).toBeVisible();
});

test("alert detail right rail shows Entities SideBlock", async ({ page }) => {
  await page.goto(`/#/alerts/${FIRST_ALERT.alert_id}`);
  // Use the right-rail aside to scope to avoid collision with sidebar "Entities" nav item
  const rightRail = page.getByRole("complementary", { name: /alert detail right rail/i });
  await expect(rightRail).toBeVisible();
  await expect(rightRail.getByText(/entities/i).first()).toBeVisible();
});

test("alert detail right rail shows MITRE ATT&CK SideBlock", async ({ page }) => {
  await page.goto(`/#/alerts/${FIRST_ALERT.alert_id}`);
  const rightRail = page.getByRole("complementary", { name: /alert detail right rail/i });
  await expect(rightRail.getByText(/mitre/i)).toBeVisible();
});

test("alert detail right rail shows AI Explanation SideBlock", async ({ page }) => {
  await page.goto(`/#/alerts/${FIRST_ALERT.alert_id}`);
  const rightRail = page.getByRole("complementary", { name: /alert detail right rail/i });
  await expect(rightRail.getByText(/ai explanation/i)).toBeVisible();
});

test("navigating from #/alerts/:id to #/alerts shows alerts screen", async ({
  page,
}) => {
  await page.goto(`/#/alerts/${FIRST_ALERT.alert_id}`);
  await expect(page.getByTestId("alert-detail-screen")).toBeVisible();

  // Navigate back to alerts list
  await page.evaluate(() => {
    window.location.hash = "#/alerts";
  });
  await expect(page.getByTestId("alerts-screen")).toBeVisible();
});

test("unknown alert id shows not-found message", async ({ page }) => {
  await page.goto("/#/alerts/nonexistent-alert-id");
  await expect(page.getByText(/alert not found/i)).toBeVisible();
});

test("acknowledge button toggles to acknowledged state", async ({ page }) => {
  await page.goto(`/#/alerts/${FIRST_ALERT.alert_id}`);
  const btn = page.getByRole("button", { name: /^acknowledge$/i });
  await btn.click();
  await expect(page.getByRole("button", { name: /acknowledged/i })).toBeVisible();
});

test("alert detail correlated events render after detail loads", async ({
  page,
}) => {
  await page.goto(`/#/alerts/${FIRST_ALERT.alert_id}`);
  // detailFor returns contributing_events with "Process launched" and "Network connection"
  await expect(page.getByText(/Process launched/i)).toBeVisible({ timeout: 5000 });
});

test("#/alerts renders AlertsScreen with alerts-screen testid", async ({ page }) => {
  await page.goto("/#/alerts");
  await expect(page.getByTestId("alerts-screen")).toBeVisible();
});
