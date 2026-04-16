// AC-10: closing the stubbed WebSocket triggers the 3s disconnect banner
// (`AlertFeed.tsx:133-141`). Driving `page.clock.fastForward` avoids wall-
// clock flake on loaded CI runners.
//
// The banner shares `role="status"` with the summary-badges connection dot,
// so every banner assertion must filter by the banner text.

import { expect, test } from "@playwright/test";
import { stubRestAlerts, stubWebSocket } from "../fixtures/stubs";

test.skip(process.env.RUN_E2E !== "1", "set RUN_E2E=1 to run");

test("disconnect banner appears 3s after WS close and hides on reconnect", async ({ page }) => {
  await stubRestAlerts(page);
  const ws = await stubWebSocket(page);

  await page.clock.install();
  await page.goto("/");

  await expect(page.getByRole("button", { name: /^alert / })).toHaveCount(5);

  const banner = page
    .getByRole("status")
    .filter({ hasText: "Live stream disconnected" });
  await expect(banner).toBeHidden();

  ws.close();
  await page.clock.fastForward(3500);
  await expect(banner).toBeVisible();

  // Reconnect timing contract: `ws.reopen()` arms a resolver that fires when
  // the next routeWebSocket callback runs. Order matters:
  //   1. Arm the resolver BEFORE advancing the clock so the reconnect
  //      attempt triggered by `useWebSocket`'s exponential backoff has
  //      something to resolve. Without the guard in `stubs.ts::reopen`
  //      (resolves immediately if `route` is already non-null), inverting
  //      this order can hang the test.
  //   2. Fast-forward past the first backoff window (useWebSocket.ts uses
  //      1s as the first delay; 2000 ms gives safety margin).
  const reopened = ws.reopen();
  await page.clock.fastForward(2000);
  await reopened;
  await expect(banner).toBeHidden();
});
