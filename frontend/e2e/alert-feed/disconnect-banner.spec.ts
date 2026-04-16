// AC-10: closing the stubbed WebSocket triggers the 3s disconnect banner
// (`AlertFeed.tsx:133-141`). Uses real timers rather than `page.clock`
// because the `useWebSocket` reconnect backoff and the WS close-event
// plumbing through `page.routeWebSocket` both tick on real wall time; a
// mocked clock desynchronises the close signal from the banner setTimeout.
//
// The banner shares `role="status"` with the summary-badges connection dot,
// so every banner assertion must filter by the banner text.

import { expect, test } from "@playwright/test";
import { stubRestAlerts, stubWebSocket } from "../fixtures/stubs";

test.skip(process.env.RUN_E2E !== "1", "set RUN_E2E=1 to run");

// Allow real 3s banner timer + reconnect cycle without hitting the default
// 30s ceiling on slow CI runners.
test.setTimeout(20_000);

test("disconnect banner appears 3s after WS close and hides on reconnect", async ({ page }) => {
  await stubRestAlerts(page);
  const ws = await stubWebSocket(page);

  await page.goto("/");

  await expect(page.getByRole("button", { name: /^alert / })).toHaveCount(5);

  const banner = page
    .getByRole("status")
    .filter({ hasText: "Live stream disconnected" });
  await expect(banner).toBeHidden();

  ws.close();
  // Banner fires on `status === "closed"` + 3000ms setTimeout. `toBeVisible`
  // polls up to 10s (configured below via assertion timeout) which covers the
  // banner's 3s delay plus the close-event propagation.
  await expect(banner).toBeVisible({ timeout: 10_000 });

  // Reconnect: `useWebSocket` retries with exponential backoff; the first
  // retry fires after ~1s. On reconnect, `page.routeWebSocket` fires the
  // handler again and `ws.reopen()` resolves. Banner hides when `status`
  // flips back to "open".
  await ws.reopen();
  await expect(banner).toBeHidden({ timeout: 10_000 });
});
