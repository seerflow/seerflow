import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  use: {
    baseURL: "http://localhost:8080",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: {
    command: "npm run preview -- --port 8080 --strictPort",
    url: "http://localhost:8080",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
  projects: [
    {
      name: "e2e",
      testDir: "./e2e",
      // Exclude legacy top-level smoke specs (`anomaly-timeline.spec.ts`,
      // `entity-explorer.spec.ts`) until their own Playwright rollout
      // stories land -- they expect a live backend and were only
      // `RUN_E2E=1`-gated to stay out of CI. The new CI job sets
      // `RUN_E2E=1` unconditionally, so an explicit ignore is required.
      testIgnore: [
        "**/quarantine/**",
        "anomaly-timeline.spec.ts",
        "entity-explorer.spec.ts",
      ],
    },
    {
      name: "quarantine",
      testDir: "./e2e/quarantine",
      retries: 2,
    },
  ],
});
