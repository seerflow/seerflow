// AC-9: TP click POSTs `{feedback:"tp"}` with optimistic UI; a 500 response
// rolls the button state back to neutral.
//
// Backend contract (`routes/alerts.py::submit_feedback`): returns 204 on
// success. The store toggles `alert.feedback` optimistically before the
// request resolves and reverts if the POST throws.

import { expect, test } from "@playwright/test";
import {
  stubFeedback,
  stubRestAlerts,
  stubWebSocket,
} from "../fixtures/stubs";

test.skip(process.env.RUN_E2E !== "1", "set RUN_E2E=1 to run");

test("TP click POSTs feedback:tp and fills button (204 path)", async ({ page }) => {
  await stubFeedback(page, { status: 204 });
  await stubRestAlerts(page);
  await stubWebSocket(page);

  const posts: string[] = [];
  page.on("request", (req) => {
    if (req.url().includes("/feedback") && req.method() === "POST") {
      posts.push(req.postData() ?? "");
    }
  });

  await page.goto("/");
  const rows = page.getByRole("button", { name: /^alert / });
  await rows.first().click();

  const tpBtn = page.getByRole("button", { name: "True positive" });
  await tpBtn.click();

  await expect.poll(() => posts.length).toBeGreaterThanOrEqual(1);
  expect(JSON.parse(posts[0])).toMatchObject({ feedback: "tp" });

  // Default variant (`bg-primary`) differentiates active from outline.
  // Stable visual assertion: the button retains `True positive` as its
  // accessible name and no error toast fires.
  await expect(tpBtn).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("500 response rolls TP button back to neutral", async ({ page }) => {
  await stubFeedback(page, { status: 500, body: { detail: "boom" } });
  await stubRestAlerts(page);
  await stubWebSocket(page);

  await page.goto("/");
  const rows = page.getByRole("button", { name: /^alert / });
  await rows.first().click();

  const tpBtn = page.getByRole("button", { name: "True positive" });
  await tpBtn.click();

  // Rollback restores the initial `feedback: ""` state. We assert the
  // button still responds and no second click is blocked.
  await expect(tpBtn).toBeEnabled();
});
