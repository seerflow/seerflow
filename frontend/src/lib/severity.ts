import type { SeverityBucket } from "./types";

export function severityBucket(id: number): SeverityBucket {
  if (id >= 17) return "critical";
  if (id >= 13) return "high";
  if (id >= 9)  return "medium";
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
