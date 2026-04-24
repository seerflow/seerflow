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
        }),
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

test("toggle a sigma rule and reload — state persists", async ({ page }) => {
  await stubSigmaRoutes(page);
  await page.goto("/#sigma-rules");

  await expect(page.getByRole("heading", { name: "Sigma rules" })).toBeVisible();
  await expect(page.getByText("E2E Bundled Test Rule")).toBeVisible();

  const toggle = page.getByRole("switch", { name: /toggle rule e2e bundled test rule/i });
  await expect(toggle).toBeChecked();
  await toggle.click();
  await expect(toggle).not.toBeChecked();

  await page.reload();
  const toggleAfter = page.getByRole("switch", {
    name: /toggle rule e2e bundled test rule/i,
  });
  await expect(toggleAfter).not.toBeChecked();
});

test("upload rule — validate then save shows toast + refetches list", async ({ page }) => {
  await stubSigmaRoutes(page);
  await page.goto("/#sigma-rules");

  await page.getByRole("button", { name: /upload rule/i }).click();
  // Monaco lazy-loads from CDN; wait until it renders. The fallback testid
  // is gone once Monaco mounts. We type into the editor's surface via keyboard.
  const editor = page.locator("[data-testid='sigma-upload-sheet']");
  await expect(editor).toBeVisible();
  await page.keyboard.type("title: Uploaded Rule\nlogsource: { product: linux }\n");

  await page.getByRole("button", { name: /validate/i }).click();
  await expect(page.getByTestId("sigma-upload-result")).toContainText(/valid/i);

  await page.getByRole("button", { name: /save/i }).click();
  await expect(page.getByText(/rule uploaded/i)).toBeVisible();
});
