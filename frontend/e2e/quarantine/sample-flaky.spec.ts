// Sample flaky spec -- proves the `quarantine` Playwright project fires
// and retries a spec without failing the CI job. If this file is deleted,
// the quarantine project becomes silently broken. Do not "fix" the flake.
//
// Quarantine escape policy (see frontend/e2e/README.md):
//   * Real quarantined specs link a tracking issue on the first line.
//   * Owner has 30 days to fix or delete.
//   * Reviewers check quarantined-spec age on every PR that touches e2e.

import { expect, test } from "@playwright/test";

test.skip(process.env.RUN_E2E !== "1", "set RUN_E2E=1 to run");

test("sample flaky -- 20% failure rate, proves quarantine retries", () => {
  // `retries: 2` in the quarantine project -> probability of a failing run
  // reaching the job summary is 0.2^3 = 0.008. Good enough for a smoke.
  expect(Math.random()).toBeGreaterThan(0.2);
});
