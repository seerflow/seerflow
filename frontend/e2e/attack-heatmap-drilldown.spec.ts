import { test, expect, type Route } from "@playwright/test";

// NOTE: The COVERAGE_PAYLOAD must match the AttackCoverageResponse wire format
// (src/lib/types.ts). The mergeCatalog function in AttackHeatmap.tsx builds the
// cellMap key as `${tactic.tactic}:${cell.technique}` (API fields), then looks
// up via `${tactic.shortname}:${tech.id}` (catalog fields). For T1053/T1059 to
// appear as covered/gap cells, tactic.tactic must equal the catalog's shortname
// "execution", and each cell's .technique must match the catalog tech id.
const COVERAGE_PAYLOAD = {
  window_since: "2026-03-23T00:00:00Z",
  window_until: "2026-04-22T00:00:00Z",
  tactics: [
    {
      tactic: "execution",
      tactic_display_name: "Execution",
      techniques: [
        { tactic: "execution", technique: "T1053", rule_count: 1, alert_count: 1, rule_names: ["windows_scheduled_task"], covered: true, detected: true },
        { tactic: "execution", technique: "T1059", rule_count: 0, alert_count: 0, rule_names: [],                         covered: false, detected: false },
      ],
    },
  ],
  summary: {
    total_techniques_covered: 1,
    total_techniques_detected: 1,
    total_rules_with_attack_tags: 1,
    total_alerts_matched: 1,
  },
};

const FIRST_ALERT  = { alert_id: "stale-1", alert_type: "sigma", rule_name: "windows_scheduled_task", severity: 4,
                       risk_score: 70, entity_uuid: "e-1", entity_type: "host", entity_value: "stale-host",
                       message: "Stale first cell alert", mitre_tactics: ["execution"], mitre_techniques: ["T1053"],
                       dedup_count: 1, timestamp_ns: "1700000000000000000" };
const SECOND_ALERT = { ...FIRST_ALERT, alert_id: "fresh-2", entity_value: "fresh-host", message: "Fresh second cell alert", mitre_techniques: ["T1059"] };

test.describe("attack-heatmap drilldown abort-race", () => {
  test("switching cells while first fetch is in flight aborts and renders only the second", async ({ page }) => {
    await page.route(/\/api\/v1\/attack\/coverage(\?.*)?$/, async (route: Route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(COVERAGE_PAYLOAD) });
    });

    let releaseFirst: (() => void) | null = null;
    const firstHeld = new Promise<void>((res) => { releaseFirst = res; });

    await page.route(/\/api\/v1\/alerts\?.*technique=T1053/, async (route: Route) => {
      await firstHeld;
      // If the request was aborted by the client, route.fulfill rejects — ignore.
      try {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [FIRST_ALERT], total: 1, limit: 20, offset: 0 }) });
      } catch { /* aborted */ }
    });
    await page.route(/\/api\/v1\/alerts\?.*technique=T1059/, async (route: Route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [SECOND_ALERT], total: 1, limit: 20, offset: 0 }) });
    });

    await page.goto("/#coverage");

    // T1053 appears in multiple tactic columns in the full ATT&CK catalog
    // (execution, persistence, privilege_escalation). Use exact aria-labels to
    // target the Execution-tactic instances specifically.
    // Open the first cell — fetch is in flight, held by `firstHeld`.
    const cellT1053 = page.getByRole("button", { name: "T1053 Scheduled Task/Job — Detected, 1 rules, 1 alerts" });
    await cellT1053.click();

    // Switch to the second cell BEFORE the first response resolves — this triggers abort.
    // Radix UI Sheet sets aria-hidden="true" on the rest of the DOM when open, so
    // getByRole won't find T1059 while the T1053 sheet is open. Use a CSS attribute
    // selector on aria-label to find the button without going through the ARIA tree,
    // then dispatchEvent to bypass the Sheet overlay's pointer-events capture.
    const cellT1059 = page.locator('[aria-label="T1059 Command and Scripting Interpreter — Gap, 0 rules, 0 alerts"]');
    await cellT1059.dispatchEvent("click");

    // Now release the held first response. The aborted fetch must not paint.
    releaseFirst!();

    // Only the second cell's content should render. The drilldown panel for T1059 has no rules
    // (covered=false), so we assert the empty-rules copy + absence of the stale alert.
    await expect(page.getByText(/No rules cover this technique/)).toBeVisible();
    await expect(page.getByText("Stale first cell alert")).toHaveCount(0);
  });
});
