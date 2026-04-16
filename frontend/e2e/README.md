# Frontend E2E (Playwright)

Playwright projects for the Seerflow dashboard. Currently covers the alert feed (S-058 + S-195); timeline, entity explorer, and KPI widgets land in follow-up stories.

## Running locally

Playwright's `webServer` config will boot `vite preview` automatically, but the two-terminal flow is faster for iterative debugging:

```bash
# Terminal 1 — serve the production build
cd frontend
npm run build
npm run preview -- --port 8080 --strictPort

# Terminal 2 — drive the suite
cd frontend
RUN_E2E=1 npm run e2e
```

`RUN_E2E=1` gates the suite so `npm run e2e` without the flag is a no-op (see `frontend/package.json`). CI sets the flag explicitly.

## Backend stubbing

Every spec stubs the backend at the network layer. **No Python process runs during E2E.**

- REST via `page.route('**/api/v1/alerts*', …)` — see `fixtures/stubs.ts::stubRestAlerts`.
- Feedback POST via `page.route('**/api/v1/alerts/*/feedback', …)` — see `stubFeedback`. Register before `stubRestAlerts` so the feedback pattern wins route matching.
- WebSocket via `page.routeWebSocket('**/api/v1/ws', …)` — see `stubWebSocket`. Returns a handle exposing `send`, `close`, `reopen`, and a `sent` array of frames the browser pushed toward the stubbed server.

The glob patterns are protocol-agnostic. Overriding `VITE_API_BASE` locally (e.g. pointing at a dev backend on another port) still routes through the stubs. **Do not change the glob to a fully-qualified URL** — the local-dev case would stop routing.

## Projects

Two Playwright projects in `playwright.config.ts`:

- **`e2e`** — the canonical suite. Failures block the CI job.
- **`quarantine`** — flaky specs live here with `retries: 2`. Failures are reported but do not block the job (`continue-on-error: true` on the CI step).

## Quarantine escape policy

Moving a spec to `quarantine/` is a last-resort mitigation, not a solution:

1. Open a tracking issue before the move.
2. Add a comment to the first line of the spec file linking the issue.
3. The owner has 30 days to fix or delete the spec.
4. Reviewers check quarantined spec ages on every PR that touches `frontend/e2e/`.

The sample flaky spec (`quarantine/sample-flaky.spec.ts`) exists to prove the project runs — do not fix it. It is gated on `RUN_E2E=1`, so the quarantine project's retry logic only exercises when the env flag is set. CI always sets the flag; locally, use `RUN_E2E=1 npx playwright test --project=quarantine` to verify.

## Three-run stability gate

The S-195 acceptance criteria call for three consecutive green runs of the `e2e` project before merge. This is **enforced by the reviewer, not by a blocking CI step** — automating a triple-matrix on every PR would triple CI cost for no real gain. Push once, observe green; push again, observe green; push again, observe green. Then merge.

## Wall-clock budget

The `frontend-e2e` job targets **< 120 s** on a warm browser cache. A cold cache (first run after a Playwright version bump) adds 30–45 s for the `playwright install` step — that is accepted as a one-PR cost.

## Trace inspection

On failure, Playwright uploads `frontend/test-results/` (traces, videos, screenshots) and `frontend/playwright-report/` (HTML report) as workflow artefacts with 7-day retention. Download the artefact, open `playwright-report/index.html` in a browser, and step through the failing trace frame by frame.

## Fixture conventions

- `timestamp_ns` is a **JSON string** on the wire (S-194 bigint-safe serialization). Fixtures write string literals, not numbers — `JSON.stringify(BigInt(x))` throws.
- Alert IDs use disjoint ranges (`wu-*` warm-up, `lp-*` live-push) so the alert-store dedup merge does not silently fail the "new row at position 0" assertion.
- Deterministic timing: filter-debounce and disconnect-banner specs drive `page.clock.install()` + `page.clock.fastForward(ms)` rather than sleeping.
- `wsFilter` singleton reset: `frontend/src/lib/wsFilter.ts` caches per-widget filter intents at module scope. Specs that assert on the filter wire shape must call `_resetForTests()` in a `beforeEach` hook so prior-spec state does not leak into the current run. See `alert-feed/filter-debounce.spec.ts` for the pattern.

## Layout

- `alert-feed/*.spec.ts` — per-journey specs for the alert-feed widget. New alert-feed journeys go here.
- `anomaly-timeline.spec.ts`, `entity-explorer.spec.ts` — legacy smoke files. **Excluded** from the `e2e` project (see `playwright.config.ts::projects[0].testIgnore`) because they expect a live backend and the new CI job does not boot one. They run only when pointed at explicitly: `RUN_E2E=1 npx playwright test e2e/anomaly-timeline.spec.ts`. When their full Playwright rollouts land in their own stories, move them to `timeline/` and `entity-explorer/` subdirectories following the alert-feed layout and drop the ignore entry.
- `fixtures/` — shared fixture data and stub factories.
- `quarantine/` — deliberately flaky specs (see policy above).
