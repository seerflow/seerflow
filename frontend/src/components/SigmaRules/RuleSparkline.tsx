// S-154 (T8): 24h match-count sparkline rendered inline as an SVG <polyline>.
//
// Consumes the dense 24-bucket grid from
// `GET /api/v1/sigma/rules/{rule_id}/timeline?bucket=hour&window=24h` (T2).
// Pure-presentational: never throws on bad data; if all counts are zero the
// component renders a flat baseline with a "no recent matches" tooltip so
// operators can distinguish "endpoint up, no fires" from a render error.
import type { JSX } from "react";

export interface SparklineBucket {
  bucket_start_ns: bigint;
  count: number;
}

interface Props {
  buckets: SparklineBucket[];
  width?: number;
  height?: number;
}

export function RuleSparkline({
  buckets,
  width = 96,
  height = 24,
}: Props): JSX.Element {
  const max = Math.max(1, ...buckets.map((b) => b.count));
  const stepX = width / Math.max(1, buckets.length - 1);
  const points = buckets
    .map((b, i) => {
      const x = i * stepX;
      const y = height - (b.count / max) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const allZero = buckets.every((b) => b.count === 0);
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="24h match-count sparkline"
    >
      {allZero ? <title>no recent matches</title> : null}
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
      />
    </svg>
  );
}
