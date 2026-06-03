// S-336 AC5/AC7: warm-up REST populates the console table; rows carry the
// `aria-label="alert {rule_name}"` hook. The summary-badge "Critical N" text
// from the S-321 feed is gone — the rebuilt console shows a KPI header
// (open/triaging/resolved + mttd/mttr/fp) and status tabs instead. Visibility
// is gated by the active status tab, so the spec lands on "All" to assert over
// the full loaded set independent of the demo-derived workflow status.

import { expect, test } from "@playwright/test";
import { stubRestAlerts, stubWebSocket } from "../fixtures/stubs";

test.skip(process.env.RUN_E2E !== "1", "set RUN_E2E=1 to run");

test("warm-up REST populates the console table under the All tab", async ({ page }) => {
  await stubRestAlerts(page);
  await stubWebSocket(page);

  await page.goto("/#/alerts");

  // All tab → every loaded alert is visible regardless of derived status.
  await page.getByRole("tab", { name: /All/ }).click();

  const rows = page.getByRole("button", { name: /^alert / });
  await expect(rows).toHaveCount(5);

  // Fixture sends alerts in ascending `timestamp_ns`; the store sorts
  // descending on backfill, so wu-005 ("Registry autorun") ends up first.
  await expect(rows.first()).toHaveAccessibleName(/Registry autorun/);

  // Demo KPI values are always rendered in the header.
  await expect(page.getByText("38s")).toBeVisible();
  await expect(page.getByText("3.2%")).toBeVisible();

  // The alert volume strip renders.
  await expect(page.getByTestId("alert-volume-strip")).toBeVisible();
});
