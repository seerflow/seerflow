// AC-8: clicking a row triggers GET /api/v1/alerts/{id}; the detail panel
// renders the rule name, message, two contributing events, three MITRE
// technique chips, and the risk score.

import { expect, test } from "@playwright/test";
import { stubRestAlerts, stubWebSocket } from "../fixtures/stubs";

test.skip(process.env.RUN_E2E !== "1", "set RUN_E2E=1 to run");

test("row click opens detail panel with events, MITRE chips, risk score", async ({ page }) => {
  await stubRestAlerts(page);
  await stubWebSocket(page);

  await page.goto("/");

  const rows = page.getByRole("button", { name: /^alert / });
  await expect(rows).toHaveCount(5);

  // Click wu-005 (newest, top row). `detailFor("wu-005")` spreads the
  // matched base alert, overriding `mitre_techniques` to the canned
  // three-chip array and attaching two contributing events. Message +
  // rule_name come from the wu-005 base ("Registry autorun" / "HKCU\\Run
  // modified").
  await rows.first().click();

  // Detail panel has no unique landmark role; query by heading + chips.
  await expect(page.getByRole("heading", { name: "Registry autorun" })).toBeVisible();
  await expect(page.getByText("Process launched")).toBeVisible();
  await expect(page.getByText("Network connection")).toBeVisible();
  await expect(page.getByText("T1059.001")).toBeVisible();
  await expect(page.getByText("T1547")).toBeVisible();
  await expect(page.getByText("T1055")).toBeVisible();
  await expect(page.getByText(/Risk score:/)).toBeVisible();
  // `risk_score.toFixed(2)` = "0.78" (backend clamps risk_score to [0, 1]).
  await expect(page.getByText(/0\.78/)).toBeVisible();
});
