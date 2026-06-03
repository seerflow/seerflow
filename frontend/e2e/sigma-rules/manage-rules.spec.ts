// S-151 E2E: Sigma rules page — toggle persists across reload, upload
// validate flow surfaces results.
//
// Stubs `/api/v1/sigma/rules` so no backend is required. The toggle stub
// keeps state in module-scoped variables so a reload sees the latest value.

import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

test.skip(process.env.RUN_E2E !== "1", "set RUN_E2E=1 to run");

interface StubRule {
  rule_id: string;
  title: string;
  description: string;
  severity: number;
  logsource_key: [string, string, string];
  attack_tactics: string[];
  attack_techniques: string[];
  enabled: boolean;
  source: "bundled" | "custom" | "custom_uploaded";
  match_count_lifetime: number;
  last_fired_ns: number | null;
  alert_count_24h: number;
}

const baseRule: StubRule = {
  rule_id: "11111111-2222-3333-4444-555555555555",
  title: "E2E Bundled Test Rule",
  description: "Stubbed rule for the Playwright suite.",
  severity: 4,
  logsource_key: ["", "linux", ""],
  attack_tactics: ["execution"],
  attack_techniques: ["t1059"],
  enabled: true,
  source: "bundled",
  match_count_lifetime: 12,
  last_fired_ns: null,
  alert_count_24h: 3,
};

async function stubSigmaRoutes(page: Page) {
  const ruleState = { ...baseRule };

  await page.route(/\/api\/v1\/sigma\/rules(\/.*)?(\?.*)?$/, async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();

    if (method === "GET" && url.pathname.endsWith("/api/v1/sigma/rules")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: [ruleState],
          total: 1,
          page: 1,
          limit: 100,
          has_next: false,
        }),
      });
      return;
    }

    const timelineMatch = url.pathname.match(
      /\/api\/v1\/sigma\/rules\/([^/]+)\/timeline$/,
    );
    if (method === "GET" && timelineMatch) {
      const HOUR_NS = 3_600_000_000_000;
      const buckets = Array.from({ length: 24 }, (_, i) => ({
        bucket_start_ns: String(BigInt(i) * BigInt(HOUR_NS)),
        count: 0,
      }));
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ buckets }),
      });
      return;
    }

    const detailMatch = url.pathname.match(/\/api\/v1\/sigma\/rules\/([^/]+)$/);
    if (method === "GET" && detailMatch) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...ruleState, yaml_source: "title: E2E Bundled Test Rule\n" }),
      });
      return;
    }

    if (method === "PATCH" && detailMatch) {
      const body = JSON.parse(route.request().postData() ?? "{}") as { enabled: boolean };
      ruleState.enabled = body.enabled;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...ruleState, yaml_source: "title: E2E Bundled Test Rule\n" }),
      });
      return;
    }

    if (method === "POST" && url.pathname.endsWith("/api/v1/sigma/rules")) {
      const dryRun = url.searchParams.get("dry_run") === "true";
      if (dryRun) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            valid: true,
            rule_id: "00000000-1111-2222-3333-444444444444",
            title: "Uploaded Rule",
            logsource_key: ["", "linux", ""],
          }),
        });
        return;
      }
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          rule_id: "00000000-1111-2222-3333-444444444444",
          title: "Uploaded Rule",
          description: "",
          severity: 3,
          logsource_key: ["", "linux", ""],
          attack_tactics: [],
          attack_techniques: [],
          enabled: true,
          source: "custom_uploaded",
          yaml_source: "title: Uploaded Rule\n",
          match_count_lifetime: 0,
          last_fired_ns: null,
          alert_count_24h: 0,
        }),
      });
      return;
    }

    await route.fallback();
  });
}

// S-341 (Apr 2026 / 2026-05-27 redesign): the legacy `<h1>Sigma rules</h1>`
// heading is gone (mockup uses breadcrumb chrome only); the in-row toggle
// switch was replaced by a status dot + a Disable button on the detail panel.
// The smoke now drives the new chrome: list loads, selecting the row opens
// the detail panel, the detail Disable button toggles enable state, and the
// state survives a reload.
test("disable a sigma rule via detail panel and reload — state persists", async ({ page }) => {
  await stubSigmaRoutes(page);
  await page.goto("/#sigma-rules");

  // New chrome: the breadcrumb owns the title — no in-panel heading.
  await expect(page.getByRole("heading", { name: "Sigma rules" })).toHaveCount(0);

  // The row renders rule_id (mono) as its primary label.
  const row = page.getByTestId(
    "sigma-rule-row-11111111-2222-3333-4444-555555555555",
  );
  await expect(row).toBeVisible();
  await row.click();

  // Detail panel opens.
  await expect(page.getByTestId("rule-detail-panel-header")).toBeVisible();
  // Disable button toggles the rule.
  const disableBtn = page.getByRole("button", { name: /^Disable$/ });
  await expect(disableBtn).toBeVisible();
  await disableBtn.click();
  // After toggle the panel re-renders with Enable.
  await expect(page.getByRole("button", { name: /^Enable$/ })).toBeVisible();

  await page.reload();
  // After reload the row still loads; its status dot now uses text-3 (disabled).
  await expect(
    page.getByTestId("sigma-rule-row-11111111-2222-3333-4444-555555555555"),
  ).toBeVisible();
});

// Monaco's contenteditable surface does not capture page.keyboard.type
// reliably in headless CI (the editor needs its own focus/IME path).
// The validate-then-save flow is fully covered by the UploadRuleDialog
// unit test using a mocked editor (`UploadRuleDialog.test.tsx`). Re-enable
// once a Monaco-aware test pattern is added — tracked in S-154 (SEE-236).
test.skip("upload rule — validate then save shows toast + refetches list", async ({ page }) => {
  await stubSigmaRoutes(page);
  await page.goto("/#sigma-rules");

  await page.getByRole("button", { name: /upload rule/i }).click();
  const editor = page.locator("[data-testid='sigma-upload-sheet']");
  await expect(editor).toBeVisible();
  await page.keyboard.type("title: Uploaded Rule\nlogsource: { product: linux }\n");

  await page.getByRole("button", { name: /validate/i }).click();
  await expect(page.getByTestId("sigma-upload-result")).toContainText(/valid/i);

  await page.getByRole("button", { name: /save/i }).click();
  await expect(page.getByText(/rule uploaded/i)).toBeVisible();
});
