/**
 * Locate the single alert whose timestamp falls inside the bucket window
 * ``[bucketStartNs, bucketStartNs + resolutionNs)``. Exported for direct
 * unit-testing of the resolution-aware predicate (finding H1).
 */
export function findAlertInBucket<A extends { timestamp_ns: number }>(
  alerts: A[],
  bucketStartNs: number,
  resolutionNs: number,
): A | undefined {
  return alerts.find(
    (a) =>
      a.timestamp_ns >= bucketStartNs &&
      a.timestamp_ns < bucketStartNs + resolutionNs,
  );
}
