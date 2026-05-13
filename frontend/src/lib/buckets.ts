import type { TimelineRange, TimelineResolution } from "./types";

export const BUCKET_NS: bigint = 60n * 1_000_000_000n;

export const RESOLUTION_NS: Record<TimelineResolution, bigint> = {
  "1m": 60n * 1_000_000_000n,
  "5m": 5n * 60n * 1_000_000_000n,
  "15m": 15n * 60n * 1_000_000_000n,
  "1h": 3600n * 1_000_000_000n,
};

export const RANGE_NS: Record<TimelineRange, bigint> = {
  "1h": 3600n * 1_000_000_000n,
  "6h": 6n * 3600n * 1_000_000_000n,
  "24h": 24n * 3600n * 1_000_000_000n,
  "7d": 7n * 24n * 3600n * 1_000_000_000n,
};

export const ALLOWED_RESOLUTIONS: Record<TimelineRange, TimelineResolution[]> = {
  "1h": ["1m"],
  "6h": ["1m", "5m"],
  "24h": ["5m", "15m"],
  "7d": ["15m", "1h"],
};

export function defaultResolution(range: TimelineRange): TimelineResolution {
  return ALLOWED_RESOLUTIONS[range][0];
}

export function bucketStartNs(ts: bigint, resolution: TimelineResolution): bigint {
  const r = RESOLUTION_NS[resolution];
  return (ts / r) * r;
}

export function rangeMs(range: TimelineRange): number {
  return Number(RANGE_NS[range] / 1_000_000n);
}

export function resolutionMs(resolution: TimelineResolution): number {
  return Number(RESOLUTION_NS[resolution] / 1_000_000n);
}
