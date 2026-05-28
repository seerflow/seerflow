// S-336 AC5/AC8: the feed no longer renders an inline detail panel. Clicking a
// row navigates to the full detail page (#/alerts/:id, AlertDetailScreen). This
// spec asserts the navigation contract only; the detail page's own content is
// covered by alert-detail.spec.ts (sibling story S-337). The TP/FP feedback
// that used to live in the inline panel is being relocated to the detail page
// in a follow-up story.

import { expect, test } from "@playwright/test";
import { stubRestAlerts, stubWebSocket } from "../fixtures/stubs";

test.skip(process.env.RUN_E2E !== "1", "set RUN_E2E=1 to run");

test("row click navigates to the alert detail route", async ({ page }) => {
  await stubRestAlerts(page);
  await stubWebSocket(page);

  await page.goto("/#/alerts");
  await page.getByRole("tab", { name: /All/ }).click();

  const rows = page.getByRole("button", { name: /^alert / });
  await expect(rows).toHaveCount(5);

  // Click the top row; the hash advances to #/alerts/<id>.
  await rows.first().click();

  await expect.poll(() => new URL(page.url()).hash).toMatch(/^#\/alerts\/.+/);

  // No inline detail panel / feedback controls remain in the feed.
  await expect(page.getByRole("button", { name: /true positive/i })).toHaveCount(0);
});
