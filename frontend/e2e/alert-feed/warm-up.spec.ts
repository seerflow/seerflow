// AC-5: warm-up REST populates five rows newest-first; severity badges
// match the fixture's {critical:2, high:1, medium:1, low:1} bucket map.
//
// Selectors locked to live markup (AlertRow.tsx: `<button aria-label="alert
// {rule_name}">`; SummaryBadges.tsx renders `{Label} {count}` text spans).

import { expect, test } from "@playwright/test";
import { stubRestAlerts, stubWebSocket } from "../fixtures/stubs";

test.skip(process.env.RUN_E2E !== "1", "set RUN_E2E=1 to run");

test("warm-up REST populates five rows with severity counts", async ({ page }) => {
  await stubRestAlerts(page);
  await stubWebSocket(page);

  await page.goto("/");

  const rows = page.getByRole("button", { name: /^alert / });
  await expect(rows).toHaveCount(5);

  // Newest-first: wu-005 (timestamp_ns ...005) is `Registry autorun`.
  await expect(rows.first()).toHaveAccessibleName(/Registry autorun/);

  // Summary badges render as "<Label> <count>" text spans. Two critical
  // (sev 20 + 18), one high (14), one medium (10), one low (5).
  await expect(page.getByText(/^Critical 2$/)).toBeVisible();
  await expect(page.getByText(/^High 1$/)).toBeVisible();
  await expect(page.getByText(/^Medium 1$/)).toBeVisible();
  await expect(page.getByText(/^Low 1$/)).toBeVisible();
});
