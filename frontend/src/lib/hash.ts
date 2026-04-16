import type { EntityViewState, TimelineRange } from "./types";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const RANGES: readonly TimelineRange[] = ["1h", "6h", "24h", "7d"];
const ALLOWED_KEYS = new Set(["entity", "range", "source", "severity"]);

export function parseEntityHash(hash: string): EntityViewState | null {
  if (!hash || hash === "#") return null;
  const trimmed = hash.startsWith("#") ? hash.slice(1) : hash;
  const params = new URLSearchParams(trimmed);
  for (const key of params.keys()) {
    if (!ALLOWED_KEYS.has(key)) return null;
  }
  const uuid = params.get("entity");
  if (!uuid || !UUID_RE.test(uuid)) return null;
  const rangeRaw = (params.get("range") ?? "24h") as TimelineRange;
  if (!RANGES.includes(rangeRaw)) return null;
  const source = params.get("source") ?? undefined;
  const severityRaw = params.get("severity");
  let severity_min: number | undefined;
  if (severityRaw != null) {
    const n = Number(severityRaw);
    if (!Number.isInteger(n) || n < 0 || n > 6) return null;
    severity_min = n;
  }
  return { entity_uuid: uuid, range: rangeRaw, source, severity_min };
}

export function serializeEntityHash(state: EntityViewState): string {
  const params = new URLSearchParams();
  params.set("entity", state.entity_uuid);
  params.set("range", state.range);
  if (state.source) params.set("source", state.source);
  if (state.severity_min != null) params.set("severity", String(state.severity_min));
  return `#${params.toString()}`;
}

export function hashHasEntity(hash: string): boolean {
  return parseEntityHash(hash) != null;
}

/**
 * Navigate to an entity detail view by assigning `window.location.hash`.
 *
 * Setting `location.hash` natively pushes onto the history stack AND fires a
 * real `hashchange` event (with populated `oldURL` / `newURL`). Using
 * `pushState` + a synthetic `HashChangeEvent` would skip the native event and
 * leave `popstate` listeners out of sync. This helper is the single writer so
 * all call sites (search, related panel, graph) stay consistent.
 */
export function navigateToEntity(uuid: string, range: TimelineRange = "24h"): void {
  // Defence in depth: server responses + localStorage are untrusted. Only
  // well-formed UUIDs may reach window.location.hash so the invariant
  // `hashHasEntity(h) === (parseEntityHash(h) !== null)` holds everywhere.
  if (!UUID_RE.test(uuid)) return;
  const nextHash = serializeEntityHash({ entity_uuid: uuid, range });
  if (window.location.hash === nextHash) return;
  window.location.hash = nextHash;
}

export function isValidEntityUuid(value: unknown): value is string {
  return typeof value === "string" && UUID_RE.test(value);
}

export function hashHasCoverage(hash: string): boolean {
  if (!hash) return false;
  const trimmed = hash.startsWith("#") ? hash.slice(1) : hash;
  return trimmed === "coverage";
}
