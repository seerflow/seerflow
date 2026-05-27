// S-336 AC7: after warm-up, push {type:"alert", data:<lp-100>} over the
// stubbed WebSocket. The new row prepends (store `prepend`) and the loaded
// count climbs from 5 to 6. Asserted under the "All" tab so the prepended row
// is visible regardless of its demo-derived workflow status. The old
// "Critical N" summary badge is gone (rebuilt KPI header / tabs).

import { expect, test } from "@playwright/test";
import { stubRestAlerts, stubWebSocket } from "../fixtures/stubs";
import { livePushAlert } from "../fixtures/alerts";

test.skip(process.env.RUN_E2E !== "1", "set RUN_E2E=1 to run");

test("WS push prepends a new row to the console table", async ({ page }) => {
  await stubRestAlerts(page);
  const ws = await stubWebSocket(page);

  await page.goto("/#/alerts");
  await page.getByRole("tab", { name: /All/ }).click();

  const rows = page.getByRole("button", { name: /^alert / });
  await expect(rows).toHaveCount(5);

  // Wire format: `timestamp_ns` as JSON string (S-194).
  ws.send({ type: "alert", data: livePushAlert });

  await expect(rows).toHaveCount(6);
  await expect(rows.first()).toHaveAccessibleName(/Mimikatz detected/);
});
