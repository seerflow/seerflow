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

  // Block reconnects so the status stays "closed" for the full 3s the
  // banner timer needs. Without this, the 1s reconnect backoff succeeds
  // before the 3s timer fires and the banner never appears.
  ws.blockReconnects();
  ws.close();
  await expect(banner).toBeVisible({ timeout: 10_000 });

  // Allow reconnect and wait for the banner to clear.
  ws.allowReconnects();
  await ws.reopen();
  await expect(banner).toBeHidden({ timeout: 10_000 });
});
