import type { SeverityBucket } from "./types";

// OCSF `SeverityLevel` (0..6) — matches `SeerflowEvent.severity_id` /
// `Alert.severity` on the wire. 5=CRITICAL and 6=FATAL fall into "critical";
// 4=ERROR is "high"; 3=WARNING is "medium"; 0=TRACE / 1=INFORMATIONAL /
// 2=NOTICE are "low". DO NOT restore the pre-S-058 OTel 1-24 thresholds —
// the backend never emits those values.
export function severityBucket(id: number): SeverityBucket {
  if (id >= 5) return "critical";
  if (id === 4) return "high";
  if (id === 3) return "medium";
  return "low";
}

export const SEVERITY_CLASS: Record<SeverityBucket, string> = {
  critical: "bg-red-600/15 text-red-600 border-red-600/40",
  high:     "bg-orange-500/15 text-orange-500 border-orange-500/40",
  medium:   "bg-yellow-500/15 text-yellow-600 border-yellow-500/40",
  low:      "bg-slate-500/15 text-slate-500 border-slate-500/40",
};

export const SEVERITY_LABEL: Record<SeverityBucket, string> = {
  critical: "Critical", high: "High", medium: "Medium", low: "Low",
};

// Numeric OCSF SeverityLevel labels (0..6). Distinct from SEVERITY_LABEL
// (keyed by 4 buckets) — the entity-detail severity-minimum ToggleGroup
// exposes the underlying numeric levels directly.
export const SEVERITY_NUM_LABEL: Record<number, string> = {
  0: "Trace",
  1: "Informational",
  2: "Notice",
  3: "Warning",
  4: "Error",
  5: "Critical",
  6: "Fatal",
};
