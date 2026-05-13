// AC-6: after warm-up, push {type:"alert", data:<lp-100>} over the stubbed
// WebSocket. The new row prepends (store `prepend`), and the critical count
// climbs from 2 to 3 (lp-100 severity=22 -> critical bucket).

import { expect, test } from "@playwright/test";
import { stubRestAlerts, stubWebSocket } from "../fixtures/stubs";
import { livePushAlert } from "../fixtures/alerts";

test.skip(process.env.RUN_E2E !== "1", "set RUN_E2E=1 to run");

test("WS push prepends new row and re-counts critical badge", async ({ page }) => {
  await stubRestAlerts(page);
  const ws = await stubWebSocket(page);

  await page.goto("/");

  const rows = page.getByRole("button", { name: /^alert / });
  await expect(rows).toHaveCount(5);
  await expect(page.getByText(/^Critical 2$/)).toBeVisible();

  // Wire format: `timestamp_ns` as JSON string (S-194).
  ws.send({ type: "alert", data: livePushAlert });

  await expect(rows).toHaveCount(6);
  await expect(rows.first()).toHaveAccessibleName(/Mimikatz detected/);
  await expect(page.getByText(/^Critical 3$/)).toBeVisible();
});
