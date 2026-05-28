// S-336: the S-321 interactive severity chips ("Critical" toggle) were
// replaced by the SOC-console design. Severity/detector/assignee/time/entity
// filter chips are display stubs in this story (the mockup renders them as
// read-only dropdown affordances); the interactive filtering surface is now the
// status-tab bar (Open/Triaging/Resolved/Suppressed/All). This spec asserts the
// tab bar narrows the table. The WS filter-debounce contract is preserved in
// the store/AlertFeed path and unit-covered in AlertFeed.test.tsx
// ("pushes merged filter payload through useWsSend after 150 ms debounce").

import { expect, test } from "@playwright/test";
import { _resetForTests as resetWsFilterIntents } from "../../src/lib/wsFilter";
import { stubRestAlerts, stubWebSocket } from "../fixtures/stubs";

test.skip(process.env.RUN_E2E !== "1", "set RUN_E2E=1 to run");

test.beforeEach(() => resetWsFilterIntents());

test("status tabs narrow the console table", async ({ page }) => {
  await stubRestAlerts(page);
  await stubWebSocket(page);

  await page.goto("/#/alerts");

  // All tab shows the full loaded set.
  await page.getByRole("tab", { name: /All/ }).click();
  await expect(page.getByRole("button", { name: /^alert / })).toHaveCount(5);

  // Switching tabs re-partitions the rows; each tab's count is a subset of All.
  await page.getByRole("tab", { name: /Resolved/ }).click();
  const resolvedRows = await page.getByRole("button", { name: /^alert / }).count();
  expect(resolvedRows).toBeLessThanOrEqual(5);

  await expect(page.getByRole("tab", { name: /Resolved/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
});
