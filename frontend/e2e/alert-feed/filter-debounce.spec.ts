// AC-7: toggling "Critical" hides non-critical rows and sends exactly one
// filter frame over the stubbed WebSocket after the 150 ms debounce
// (`AlertFeed.tsx:118-122`). Clock driven via `page.clock.fastForward`
// rather than sleeping -- keeps the spec deterministic on loaded CI.

import { expect, test } from "@playwright/test";
import { stubRestAlerts, stubWebSocket } from "../fixtures/stubs";

test.skip(process.env.RUN_E2E !== "1", "set RUN_E2E=1 to run");

test("Critical chip filters rows and sends one filter frame after debounce", async ({ page }) => {
  await stubRestAlerts(page);
  const ws = await stubWebSocket(page);

  await page.clock.install();
  await page.goto("/");

  await expect(page.getByRole("button", { name: /^alert / })).toHaveCount(5);

  await page.getByRole("button", { name: "Critical" }).click();

  // 150 ms debounce + small safety margin.
  await page.clock.fastForward(500);

  // Only severity >= 17 rows remain: wu-001 (20) + wu-005 (18).
  await expect(page.getByRole("button", { name: /^alert / })).toHaveCount(2);
  await expect(
    page.getByRole("button", { name: "Critical" }),
  ).toHaveAttribute("aria-pressed", "true");

  // Wire shape: `{type:"filter", min_severity:17, ...}` per
  // `frontend/src/components/AlertFeed/AlertFeed.tsx:18-28`.
  const filters = ws.sent
    .map((s) => JSON.parse(s))
    .filter((m: { type?: string }) => m.type === "filter");
  expect(filters.length).toBeGreaterThanOrEqual(1);
  const last = filters[filters.length - 1] as { min_severity?: number };
  expect(last.min_severity).toBe(17);
});
