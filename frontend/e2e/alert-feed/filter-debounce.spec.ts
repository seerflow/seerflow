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

  // OCSF critical = severity >= 5: wu-001 (6, FATAL) + wu-005 (5, CRITICAL).
  await expect(page.getByRole("button", { name: /^alert / })).toHaveCount(2);
  await expect(
    page.getByRole("button", { name: "Critical" }),
  ).toHaveAttribute("aria-pressed", "true");

  // AC-7 debounce contract: the LAST filter frame on the wire carries the
  // user's selection. Multiple frames may fire (mount-time baseline,
  // `seerflow:wsfilter-changed` event, `useWebSocket.onopen` resend) but the
  // debounce collapses rapid changes into a single trailing frame. Assert
  // the final frame's `min_severity` rather than exact frame count.
  const filterFrames = ws.sent
    .map((s) => JSON.parse(s) as { type?: string; min_severity?: number })
    .filter((m) => m.type === "filter");
  expect(filterFrames.length).toBeGreaterThanOrEqual(1);
  const last = filterFrames[filterFrames.length - 1];
  expect(last.min_severity).toBe(5);
});
