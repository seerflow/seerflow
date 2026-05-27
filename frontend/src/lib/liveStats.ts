/**
 * S-328 — live-data selectors with demo fallback.
 *
 * Pure functions that read whatever the store/endpoint exposes and degrade to
 * the existing demo constants when the live value is absent (0 / "—" / null /
 * fetch failure). This keeps the four target screens thin and guarantees the
 * demo-mode render is byte-identical to today (AC5).
 *
 * No live writer for the status-store metrics or the `/explain` endpoint exists
 * yet (deferred backend work); these helpers are the seam the backend will
 * eventually feed without further UI changes.
 */
import { api } from "@/lib/api";
import type { EntityEvent, RiskBucket } from "@/lib/types";

// ── Demo fallback constants ───────────────────────────────────────────────────
// Mirror the existing OverviewScreen demo numbers so demo mode is unchanged.

export const DEMO_ACTIVE_ENTITIES = 3_294;
export const DEMO_MEAN_LATENCY_MS = 38;
export const DEMO_UPTIME_LABEL = "4d 12h";
export const DEMO_EVENTS_PER_SEC = 12_847;

/** Maximum OTel/OCSF severity_id; used to normalise a 0-6 severity to 0-1. */
const MAX_SEVERITY_ID = 6;

// ── AC1: Overview KPI selectors ───────────────────────────────────────────────

/** Live active-entity count, or the demo constant when no live value is present. */
export function selectActiveEntities(live: number): number {
  return live > 0 ? live : DEMO_ACTIVE_ENTITIES;
}

/** Live mean ingest latency (ms), or the demo constant when unavailable. */
export function selectMeanLatencyMs(live: number): number {
  return live > 0 ? live : DEMO_MEAN_LATENCY_MS;
}

// ── AC2: Sidebar health selector ──────────────────────────────────────────────

export interface SidebarHealth {
  uptimeLabel: string;
  evPerSec: number;
}

/**
 * Resolve the sidebar footer health, degrading each field independently to its
 * demo fallback when the live store value is at its unknown default
 * (`"—"` uptime / `0` events-per-second).
 */
export function selectSidebarHealth(live: SidebarHealth): SidebarHealth {
  return {
    uptimeLabel: live.uptimeLabel && live.uptimeLabel !== "—" ? live.uptimeLabel : DEMO_UPTIME_LABEL,
    evPerSec: live.evPerSec > 0 ? live.evPerSec : DEMO_EVENTS_PER_SEC,
  };
}

// ── AC3: Focal-entity stats selector ──────────────────────────────────────────

export interface FocalEntityStats {
  risk: number;
  eventCount: number;
  alertCount: number;
}

/**
 * Compute the focal entity's inspector stats from the entity store's timeline
 * data:
 *   - eventCount: the server `total` when known, else the loaded events length
 *   - alertCount: the sum of per-bucket alert counts in the risk history
 *   - risk:       the highest event severity normalised to [0,1] (the only risk
 *                 signal carried by entity timeline events)
 */
export function selectFocalEntityStats(
  events: EntityEvent[],
  total: number,
  riskHistory: RiskBucket[],
): FocalEntityStats {
  const eventCount = total > 0 ? total : events.length;
  const alertCount = riskHistory.reduce((sum, b) => sum + b.alert_count, 0);
  const maxSeverity = events.reduce((m, e) => (e.severity_id > m ? e.severity_id : m), 0);
  const risk = Math.min(1, maxSeverity / MAX_SEVERITY_ID);
  return { risk, eventCount, alertCount };
}

// ── AC4: LLM-explain endpoint helper ──────────────────────────────────────────

interface ExplainResponse {
  narrative: string;
}

function isExplainResponse(x: unknown): x is ExplainResponse {
  return (
    x !== null &&
    typeof x === "object" &&
    typeof (x as Record<string, unknown>).narrative === "string"
  );
}

/**
 * Fetch the LLM-generated alert explanation. Returns the narrative string when
 * the endpoint is available and well-formed, otherwise `null` — never throws,
 * never logs — so the caller can silently fall back to the demo narrative when
 * the backend route is absent (AC4 / AC5).
 */
export async function fetchAlertExplanation(
  alertId: string,
  signal?: AbortSignal,
): Promise<string | null> {
  try {
    const body = await api.get<unknown>(
      `/api/v1/alerts/${alertId}/explain`,
      { signal },
    );
    return isExplainResponse(body) ? body.narrative : null;
  } catch {
    return null;
  }
}
