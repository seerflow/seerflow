/**
 * Locate the single alert whose timestamp falls inside the bucket window
 * ``[bucketStartNs, bucketStartNs + resolutionNs)``. Accepts either bigint or
 * number `timestamp_ns` so that consumers of bigint-typed Alerts (S-194) and
 * legacy number-typed events both work.
 */
export function findAlertInBucket<A extends { timestamp_ns: bigint | number }>(
  alerts: A[],
  bucketStartNs: number,
  resolutionNs: number,
): A | undefined {
  const start = BigInt(bucketStartNs);
  const end = BigInt(bucketStartNs + resolutionNs);
  return alerts.find((a) => {
    const ts = typeof a.timestamp_ns === "bigint" ? a.timestamp_ns : BigInt(a.timestamp_ns);
    return ts >= start && ts < end;
  });
}
