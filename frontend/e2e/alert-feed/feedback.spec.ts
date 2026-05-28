/**
 * S-339: feedback E2E — relocated to the alert *detail page*.
 *
 * The TP/FP feedback UI used to live in the AlertFeed inline detail panel,
 * which S-336 removed. The S-339 follow-up re-mounts it at `#/alerts/:id` in
 * a "Verdict" SideBlock above the Entities rail. These specs assert the same
 * optimistic-fill + 5xx-rollback contract the AlertFeed version did, now
 * against the detail screen.
 *
 * Backend contract (`routes/alerts.py::submit_feedback`): returns 204 on
 * success; the store toggles `alert.feedback` optimistically and reverts on a
 * thrown POST. The history (`GET /feedback`) is fetched on mount + after
 * every successful submit (driven by `feedbackVersion` bump).
 */

import { expect, test, type Page } from "@playwright/test";
import { stubRestAlerts, stubWebSocket } from "../fixtures/stubs";
import { warmUpAlerts } from "../fixtures/alerts";

test.skip(process.env.RUN_E2E !== "1", "set RUN_E2E=1 to run");
test.setTimeout(30_000);

const ALERT = warmUpAlerts[0];
const ALERT_URL = `/#/alerts/${ALERT.alert_id}`;

/**
 * Route the feedback endpoints: GET history (always empty) and POST with the
 * caller-chosen status. We register before `stubRestAlerts` so the more
 * specific `/feedback` matcher wins over the generic alerts matcher.
 */
async function routeFeedback(
  page: Page,
  postStatus: number,
): Promise<void> {
  await page.route(/\/api\/v1\/alerts\/[^/]+\/feedback(\?.*)?$/, async (route) => {
    const method = route.request().method();
    if (method === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: [],
          total: 0,
          page: 1,
          limit: 5,
          has_next: false,
        }),
      });
      return;
    }
    if (method === "POST") {
      const body =
        postStatus === 204
          ? ""
          : JSON.stringify({ detail: "server error" });
      await route.fulfill({
        status: postStatus,
        contentType: postStatus === 204 ? "text/plain" : "application/json",
        body,
      });
      return;
    }
    await route.fallback();
  });
}

test.describe("alert detail feedback (S-339)", () => {
  test("TP click POSTs feedback:tp and reflects pressed state (204 path)", async ({
    page,
  }) => {
    await routeFeedback(page, 204);
    await stubRestAlerts(page, warmUpAlerts);
    await stubWebSocket(page);

    const postWaiter = page.waitForRequest(
      (req) =>
        /\/api\/v1\/alerts\/[^/]+\/feedback$/.test(req.url()) &&
        req.method() === "POST",
    );

    await page.goto(ALERT_URL);
    await expect(page.getByTestId("alert-detail-screen")).toBeVisible();

    const tp = page.getByRole("button", { name: /true positive/i });
    await tp.click();

    const req = await postWaiter;
    expect(JSON.parse(req.postData() ?? "{}")).toMatchObject({
      feedback: "tp",
      origin: "dashboard",
    });

    await expect(tp).toHaveAttribute("aria-pressed", "true");
  });

  test("500 response rolls TP button back to neutral", async ({ page }) => {
    await routeFeedback(page, 500);
    await stubRestAlerts(page, warmUpAlerts);
    await stubWebSocket(page);

    await page.goto(ALERT_URL);
    await expect(page.getByTestId("alert-detail-screen")).toBeVisible();

    const tp = page.getByRole("button", { name: /true positive/i });
    await tp.click();

    // After the 500 rollback completes the optimistic fill is reverted —
    // the button returns to the unpressed (outline) variant.
    await expect(tp).toHaveAttribute("aria-pressed", "false");
  });
});
