import type { Alert } from "@/lib/types";
import { severityBucket } from "@/lib/severity";

/**
 * Demo-fallback helpers for the alert console (S-336).
 *
 * The alert store / WS feed does not (yet) carry owner, status-workflow, or
 * MTTD/MTTR/FP fields. Rather than ship blank columns, these pure helpers
 * derive stable, deterministic values from the live alert so the SOC console
 * renders exactly like the approved mockup without any backend dependency or
 * console errors. Everything here is keyed off `alert_id` so a given alert
 * always shows the same owner/status across renders.
 *
 * When the backend grows real columns, swap these call sites for the live
 * fields — the component contracts stay the same.
 */

export type AlertStatus = "open" | "triaging" | "resolved" | "suppressed";

/** Demo KPI values (no backend metric source yet) — match the mockup. */
export const KPI = { mttd: "38s", mttr: "14m", fpRate: "3.2%" } as const;

/** Demo analyst roster used for the Owner column. */
const OWNERS = ["jt", "mr", "ek"] as const;

/** FNV-1a 32-bit hash — small, deterministic, no deps. */
function hashId(id: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < id.length; i++) {
    h ^= id.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/**
 * Deterministically assign an owner (or none) to an alert id. Roughly a third
 * of alerts are unassigned (rendered as the dashed "—" in the mockup).
 */
export function deriveOwner(id: string): string | null {
  const h = hashId(id);
  if (h % 3 === 0) return null;
  return OWNERS[h % OWNERS.length];
}

/**
 * Derive a triage workflow status. Critical alerts skew toward open/triaging;
 * lower-severity alerts skew resolved. Deterministic per alert id.
 */
export function deriveStatus(alert: Alert): AlertStatus {
  const bucket = severityBucket(alert.severity);
  const h = hashId(alert.alert_id);
  if (bucket === "critical") return h % 3 === 0 ? "triaging" : "open";
  if (bucket === "high") return h % 2 === 0 ? "open" : "triaging";
  if (bucket === "medium") return h % 3 === 0 ? "suppressed" : "resolved";
  return "resolved";
}

export interface EntityChip {
  kind: string;
  value: string;
}

/** Map the alert's single live entity ref to the chip list the row renders. */
export function entityChips(alert: Alert): EntityChip[] {
  if (!alert.entity_value && !alert.entity_type) return [];
  if (!alert.entity_value) return [];
  return [{ kind: alert.entity_type ?? "host", value: alert.entity_value }];
}

const SECOND_NS = 1_000_000_000n;
const MINUTE_NS = 60n * SECOND_NS;
const HOUR_NS = 60n * MINUTE_NS;
const DAY_NS = 24n * HOUR_NS;

/**
 * Compact relative timestamp for the Updated column — like the mockup's
 * "12s" / "2m" / "3h" (no "ago" suffix). Distinct from lib/relativeTime's
 * `formatRelative`, which appends "ago" and is used elsewhere.
 */
export function compactUpdated(timestamp_ns: bigint, now_ns: bigint = BigInt(Date.now()) * 1_000_000n): string {
  const delta = now_ns - timestamp_ns;
  if (delta < SECOND_NS) return "now";
  if (delta < MINUTE_NS) return `${delta / SECOND_NS}s`;
  if (delta < HOUR_NS) return `${delta / MINUTE_NS}m`;
  if (delta < DAY_NS) return `${delta / HOUR_NS}h`;
  return `${delta / DAY_NS}d`;
}

export interface TabCounts {
  open: number;
  triaging: number;
  resolved: number;
  suppressed: number;
  all: number;
}

/**
 * Tab counts for the status bar. open/triaging/resolved are derived from the
 * loaded set via `deriveStatus`; suppressed is a derived bucket (also from the
 * loaded set), and `all` is their sum. With no backend status column the totals
 * cannot exceed the loaded set, which is the honest demo behaviour.
 */
export function tabCounts(alerts: readonly Alert[]): TabCounts {
  const counts: TabCounts = { open: 0, triaging: 0, resolved: 0, suppressed: 0, all: 0 };
  for (const a of alerts) {
    counts[deriveStatus(a)]++;
  }
  counts.all = counts.open + counts.triaging + counts.resolved + counts.suppressed;
  return counts;
}
