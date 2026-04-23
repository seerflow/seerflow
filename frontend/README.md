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

### Entity Explorer

Investigator surface wired over the `GET /api/v1/entities/search` and
`GET /api/v1/entities/{uuid}/timeline` endpoints (S-060, FR-036).

- Persistent search combobox in the header (debounced, recent-searches
  in `localStorage` under `seerflow:recentEntities`, keyboard navigation).
- Entity detail view activated by URL hash:
  `#entity=<uuid>&range=24h&source=<src>&severity=<n>`. Browser
  Back / Forward and URL sharing both work.
- Cross-source timeline (virtualized via `@tanstack/react-virtual` when
  the page exceeds 200 rows), related-entities sidebar grouped by
  `relation_type`, and a one-hop force-directed graph rendered with
  `d3-force` over SVG.

Click a related entity or a graph node to pivot to that entity's
detail view. Click-to-navigate is the core interaction; richer graph
gestures (drag-to-pin, wheel-zoom, keyboard pan) land in a follow-up
story.

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

### Feedback buttons

Every alert row has compact `✓` / `✗` icon buttons at the right edge. Clicking
them sends a TP/FP verdict straight to `POST /api/v1/alerts/{id}/feedback`
without expanding the row. A sonner toast confirms the click.

Expanding a row shows the **Feedback history** section — a newest-first list of
every prior verdict (badge + origin chip + relative timestamp). The list is
backed by `GET /api/v1/alerts/{id}/feedback` and refetches whenever a new
verdict lands. The `origin` field (`dashboard` / `cli` / `api`) shows where the
verdict came from.

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

## Event Stream

The Event Stream widget renders raw pipeline events newest-first, like `tail -f`
over the entire log fleet.

- **Live ingestion:** consumes `event` and `batch` WS messages from
  `/api/v1/ws` (shared connection owned by `AlertFeed` — no second socket).
- **Warm-up:** REST `GET /api/v1/events?limit=100` on mount.
- **Filters:**
  - **Sources** — chip multi-select of every distinct `source_type` observed.
  - **Min severity** — segmented select 0–6.
  - **Template IDs** — free-form numeric chip input.
  Filter changes push a merged `filter` WS message via `lib/wsFilter` so the
  server stops sending non-matching events for any widget.
- **Pause / Resume:** pause halts visible appends; new events accumulate in a
  `pausedBuffer` (capped at 5000 — oldest evicted past the cap). Resume
  prepends the buffer and truncates to the 1000-event ring.
- **Virtualization:** `@tanstack/react-virtual` keeps DOM cost flat at high
  ingest rates.

Run end-to-end:

```bash
# terminal 1 — backend
uv run python -m seerflow start

# terminal 2 — frontend
cd frontend && npm run dev
# → http://localhost:5173 (Vite proxies /api → :8080)
```

## Widget Grid

Configurable dashboard grid (S-062, FR-038 + FR-068) driven by
`react-grid-layout`. Four core widgets mount by default — **Alert feed**,
**Anomaly timeline**, **Entity explorer**, **Event stream** — and two
optional widgets (**ATT&CK coverage**, **Source health**) can be added
from the header menu.

### Controls

- **Drag** — grab a widget by its title bar (handle shown on hover). Neighbours
  auto-pack on drop.
- **Resize** — drag the corner grip.
- **Add widget** — header `+ Add widget` dropdown lists unmounted widgets.
  Clicking one appends at the next free slot.
- **Remove widget** — the `×` button in each widget's title bar. Removed
  widgets re-appear in the Add menu.
- **Reset layout** — header `Reset layout` button (opens a confirm dialog;
  confirming restores the default 4-widget layout).

### Persistence

Layout state (widgets + per-breakpoint positions) persists to `localStorage`
under the key `seerflow.dashboard.layout.v1`. A Valibot schema guards
rehydrate — any mismatch falls back to the default layout and logs a
warning. Tab-to-tab live sync is not implemented; both tabs hydrate from
the same key on initial load.

### Breakpoints

`react-grid-layout` responsive breakpoints:

| Breakpoint | Min width | Columns |
|------------|-----------|---------|
| `lg`       | 1280 px   | 12      |
| `md`       | 768 px    | 10      |
| `sm`       | 0 px      | 6       |

Row height is 64 px; margin is 12 px.

### Empty-state recovery

Removing every widget renders a recovery card ("Your dashboard is empty…")
with a focus-forwarded `Reset layout` button, so the user is never stuck.

### Known gap: keyboard drag

`react-grid-layout` does not ship a keyboard-drag implementation. Add /
remove / reset are fully keyboard-accessible (dropdown + `×` button +
confirm dialog), so operators can still reach any layout indirectly;
true keyboard reordering is a follow-up story.

### End-to-end tests

Playwright smoke at `frontend/e2e/widget-grid.spec.ts` exercises add /
remove / reset / empty-state / persistence. Gated with `RUN_E2E=1` to
stay out of the fast Vitest lane:

```sh
cd frontend && RUN_E2E=1 npx playwright test e2e/widget-grid.spec.ts
```

The spec uses `stubRestAlerts` + `stubWebSocket` from
`e2e/fixtures/stubs.ts`; no live backend needed.

### ATT&CK Coverage

- The heatmap is reachable from the header shield (`#coverage`) and from the optional widget catalog entry "ATT&CK coverage".
- Click any technique cell to open a side panel listing the rules that cover the technique and the most recent 20 alerts that matched it within the current coverage window (default last 30 days, taken straight from the `/api/v1/attack/coverage` response).
- Clicking an alert row in the panel closes the panel, sets the selected alert in the Alert Feed widget, and navigates back to the dashboard grid (`#`). If the Alert Feed widget is not currently mounted in the grid, the panel surfaces an inline note — add the widget once to inspect future selections.
- The panel keeps an in-memory cache keyed by `(tactic, technique, since, until)`. Reopening the same cell within a session does not refetch.
- **Known gap:** sub-techniques (e.g. `T1053.005`) are not rolled up into their parent technique today. Clicking a parent cell may show "0 alerts" while sub-technique alerts exist. Tracked for a separate backend story.

## Deferred dependencies (YAGNI)

These libraries are reserved for downstream sprint stories and are
intentionally NOT installed by this scaffold story:

| Library | Lands in | Purpose |
|---------|----------|---------|
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
