/**
 * Locate the single alert whose timestamp falls inside the bucket window
 * ``[bucketStartNs, bucketStartNs + resolutionNs)``. Accepts either bigint or
 * number `timestamp_ns` and `bucketStartNs` so that consumers of bigint-typed
 * Alerts (S-194 / S-199) and legacy number-typed events both work.
 */
export function findAlertInBucket<A extends { timestamp_ns: bigint | number }>(
  alerts: A[],
  bucketStartNs: bigint | number,
  resolutionNs: bigint | number,
): A | undefined {
  const start = typeof bucketStartNs === "bigint" ? bucketStartNs : BigInt(bucketStartNs);
  const res = typeof resolutionNs === "bigint" ? resolutionNs : BigInt(resolutionNs);
  const end = start + res;
  return alerts.find((a) => {
    const ts = typeof a.timestamp_ns === "bigint" ? a.timestamp_ns : BigInt(a.timestamp_ns);
    return ts >= start && ts < end;
  });
}
