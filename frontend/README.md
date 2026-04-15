# Seerflow Dashboard (frontend)

React + TypeScript + Vite frontend for the Seerflow dashboard
(FR-033, FR-068). The production build lands in
`../src/seerflow/web/dist/` and is served by the FastAPI backend at
`http://localhost:8080/`. There is no Node.js process at runtime — the
wheel bundles the built assets.

## Toolchain

- Node 20 LTS (pinned in `.nvmrc`)
- npm ≥ 10 (ships with Node 20)

## Scripts

- `npm ci` — install exact dependency versions
- `npm run dev` — Vite dev server on port 5173 with `/api` proxy to
  `127.0.0.1:8080` (HTTP and WebSocket). Run `seerflow start`
  separately for the backend.
- `npm run build` — production build into `../src/seerflow/web/dist/`
- `npm test` — Vitest unit tests
- `npm run typecheck` — `tsc --noEmit`
- `npm run lint` — ESLint, zero warnings allowed

### Anomaly Timeline

Live time-series chart of anomaly scores (S-059). Powered by:

- `GET /api/v1/anomaly/timeline?range={1h|6h|24h|7d}&resolution={1m|5m|15m|1h}&source=…`
  on mount and on range / source change.
- WebSocket `event` messages with `score != null` for live tailing.

Data is ephemeral: a pipeline restart empties the in-memory ring, so
the chart shows "No scored events in this range" until new scores
arrive.

Allowed (range, resolution) combinations:

| Range | Resolutions |
|-------|-------------|
| 1h    | 1m          |
| 6h    | 1m, 5m      |
| 24h   | 5m, 15m     |
| 7d    | 15m, 1h     |

The "Custom…" chip is stubbed for a follow-up story.

### Alert Feed

Live alert feed widget (S-058) runs against the backend over HTTP +
WebSocket. For hot-reload development:

1. Start the backend on port 8080 in one terminal:

   ```sh
   uv run seerflow start
   # or (if the package is installed on PATH)
   seerflow start
   ```

2. Start the Vite dev server in another terminal:

   ```sh
   cd frontend && npm run dev
   ```

3. Open http://localhost:5173 — Vite proxies `/api` (REST) and
   `/api/v1/ws` (WebSocket, `ws: true` in `vite.config.ts`) through
   to `http://127.0.0.1:8080`, so the dashboard talks to the real
   backend without CORS gymnastics.

## Architecture notes

- **Path alias:** `@/` resolves to `src/` in both `vite.config.ts`
  and `tsconfig.json`. shadcn-generated imports (`@/components/ui/...`,
  `@/lib/utils`) depend on this.
- **Theme:** CSS custom properties on `:root` and
  `[data-theme="dark"]`. A tiny inline script in `index.html` reads
  `localStorage.seerflow.theme` and applies `data-theme` before the
  bundle parses to avoid a flash of the wrong palette.
- **State:** Zustand. `src/stores/theme.ts` is the baseline pattern
  (synchronous side-effect `apply()` wrapper + `localStorage`
  persistence). Widget stories should add new stores under
  `src/stores/`.
- **UI primitives:** shadcn/ui, copied into `src/components/ui/`.
  Regenerate via `npx shadcn@2.1.8 add <component>`; the version is
  pinned to keep generated output stable across contributors.

## Deferred dependencies (YAGNI)

These libraries are reserved for downstream sprint stories and are
intentionally NOT installed by this scaffold story:

| Library | Lands in | Purpose |
|---------|----------|---------|
| `d3` | S-060 | entity force-directed graph |
| `react-grid-layout` | S-062 | widget grid |
| `@tanstack/react-table` | S-058 / S-061 | alert / event tables |

Installing them now would risk a stale lockfile by the time those
stories land.

## Building the wheel with the dashboard

From the repository root:

```sh
./build_frontend.sh                        # produces src/seerflow/web/dist/
SEERFLOW_REQUIRE_FRONTEND=1 \
  uv run python preflight_wheel.py         # optional gate
uv build --wheel                           # ships web/dist inside the wheel
```

Use `uv build --wheel`, not plain `uv build`, because the default
flow builds an sdist first and the gitignored `web/dist/` does not
make it into the sdist.

## Known gaps (deferred)

- **CSP headers** — the inline theme-bootstrap script in `index.html`
  makes a strict CSP slightly harder to adopt. Tracked as an
  API-hardening follow-up.
- **CI enforcement** — `scripts/build_frontend.sh` must be run
  manually before `uv build --wheel`. A GitHub Actions workflow
  wrapper lands in a sprint-hardening story. Use the preflight gate
  locally to fail fast.
- **Asset `Cache-Control` tuning** — hashed bundle files would
  benefit from `Cache-Control: public, max-age=31536000, immutable`
  and `index.html` should be `no-cache`. Starlette `StaticFiles`
  uses defaults. Negligible until real widgets ship; deferred.
- **`npm audit` moderate advisories** — transitive `esbuild` issue
  in Vite's dev server (development-only). No HIGH/CRITICAL. Will
  clear naturally when Vite 6+ lands in a future upgrade story.
