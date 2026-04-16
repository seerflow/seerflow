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

  // Reconnect: fast-forward past the first exponential-backoff attempt.
  await page.clock.fastForward(2000);
  await ws.reopen();
  await expect(banner).toBeHidden();
});
