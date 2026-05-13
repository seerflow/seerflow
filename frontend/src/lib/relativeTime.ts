const SECOND_NS = 1_000_000_000n;
const MINUTE_NS = 60n * SECOND_NS;
const HOUR_NS = 60n * MINUTE_NS;
const DAY_NS = 24n * HOUR_NS;

function asNs(input: bigint | number): bigint {
  return typeof input === "bigint" ? input : BigInt(input) * 1_000_000n;
}

export function formatRelative(
  timestamp: bigint | number,
  now: bigint | number = Date.now()
): string {
  const ts = asNs(timestamp);
  const ref = asNs(now);
  const delta = ref - ts;

  if (delta < 0n) return "in the future";
  if (delta < SECOND_NS) return "just now";
  if (delta < MINUTE_NS) return `${delta / SECOND_NS}s ago`;
  if (delta < HOUR_NS) return `${delta / MINUTE_NS}m ago`;
  if (delta < DAY_NS) return `${delta / HOUR_NS}h ago`;
  return `${delta / DAY_NS}d ago`;
}
