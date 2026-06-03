/**
 * S-339: detail-page feedback E2E — TP click shows toast and appears in
 * history.
 *
 * Stubs the history GET to return the new TP row after the POST, then asserts
 * the row renders in the Verdict block.
 */

import { expect, test, type Page } from "@playwright/test";
import { stubRestAlerts, stubWebSocket } from "./fixtures/stubs";
import { warmUpAlerts } from "./fixtures/alerts";

test.skip(process.env.RUN_E2E !== "1", "set RUN_E2E=1 to run");
test.setTimeout(30_000);

const ALERT = warmUpAlerts[0];
const ALERT_URL = `/#/alerts/${ALERT.alert_id}`;

async function routeFeedbackFlow(page: Page): Promise<void> {
  let posted = false;
  await page.route(/\/api\/v1\/alerts\/[^/]+\/feedback(\?.*)?$/, async (route) => {
    const method = route.request().method();
    if (method === "GET") {
      const items = posted
        ? [
            {
              id: 1,
              feedback: "tp",
              note: "",
              origin: "dashboard",
              submitted_at_ns: "1700000000000000000",
            },
          ]
        : [];
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items,
          total: items.length,
          page: 1,
          limit: 5,
          has_next: false,
        }),
      });
      return;
    }
    if (method === "POST") {
      posted = true;
      await route.fulfill({ status: 204, body: "" });
      return;
    }
    await route.fallback();
  });
}

test.describe("feedback flow (S-339 detail page)", () => {
  test("TP click shows toast and appears in history", async ({ page }) => {
    await routeFeedbackFlow(page);
    await stubRestAlerts(page, warmUpAlerts);
    await stubWebSocket(page);

    await page.goto(ALERT_URL);
    await expect(page.getByTestId("alert-detail-screen")).toBeVisible();

    // Initial state: no history rows visible.
    await expect(page.getByTestId("feedback-history-row")).toHaveCount(0);

    await page.getByRole("button", { name: /true positive/i }).click();

    // Sonner toast.
    await expect(page.getByText(/Marked as true positive/i)).toBeVisible();

    // History refetch after bumpFeedbackVersion → row appears.
    await expect(page.getByTestId("feedback-history-row")).toHaveCount(1);
  });
});
