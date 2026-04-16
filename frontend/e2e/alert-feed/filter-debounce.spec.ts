// AC-7: toggling "Critical" hides non-critical rows and sends exactly one
// filter frame over the stubbed WebSocket after the 150 ms debounce
// (`AlertFeed.tsx:118-122`). Clock driven via `page.clock.fastForward`
// rather than sleeping -- keeps the spec deterministic on loaded CI.

import { expect, test } from "@playwright/test";
import { _resetForTests as resetWsFilterIntents } from "../../src/lib/wsFilter";
import { stubRestAlerts, stubWebSocket } from "../fixtures/stubs";

test.skip(process.env.RUN_E2E !== "1", "set RUN_E2E=1 to run");

// `wsFilter.ts` stores per-widget intents in a module-level singleton. Specs
// running in the same worker process would otherwise see leaked state from a
// previous test and observe a non-empty `min_severity` before the "Critical"
// chip is ever clicked. The exported helper resets the singleton.
test.beforeEach(() => resetWsFilterIntents());

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

  // AC-7 debounce contract: exactly one `filter` frame carrying a
  // `min_severity` fires per debounce window. AlertFeed's mount-time
  // useEffect (`AlertFeed.tsx:118-122`) emits an initial empty frame with no
  // `min_severity`; that baseline frame is filtered out so the assertion
  // targets only the post-click debounce output.
  const criticalFrames = ws.sent
    .map((s) => JSON.parse(s) as { type?: string; min_severity?: number })
    .filter((m) => m.type === "filter" && m.min_severity !== undefined);
  expect(criticalFrames).toHaveLength(1);
  expect(criticalFrames[0].min_severity).toBe(17);
});
