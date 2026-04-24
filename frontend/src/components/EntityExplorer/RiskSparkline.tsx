import { LineChart, Line, Tooltip, ResponsiveContainer } from "recharts";
import type { RiskBucket, TimelineRange } from "@/lib/types";

interface Props {
  data: RiskBucket[];
  loading: boolean;
  error: string | null;
  range: TimelineRange;
  label: string;
}

function fmtBucket(bucketNs: string): string {
  const ms = Number(BigInt(bucketNs) / 1_000_000n);
  return new Date(ms).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function TooltipContent({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload: RiskBucket }[];
}) {
  if (!active || !payload?.length) return null;
  const b = payload[0].payload;
  return (
    <div className="rounded border bg-popover p-2 text-xs">
      <div className="font-mono">{fmtBucket(b.bucket_start_ns)}</div>
      <div>Risk {Math.round(b.points * 10) / 10}</div>
      <div>
        {b.alert_count} alert{b.alert_count === 1 ? "" : "s"}
      </div>
      <div className="text-muted-foreground">{b.top_rule_name || "—"}</div>
    </div>
  );
}

export function RiskSparkline({ data, loading, error, range, label }: Props) {
  if (loading) {
    return (
      <div
        role="status"
        aria-label="Loading risk history"
        className="ml-auto h-12 w-40 animate-pulse rounded bg-muted/20"
      />
    );
  }
  if (error) {
    return (
      <span className="ml-auto text-xs text-destructive">
        Risk history unavailable
      </span>
    );
  }
  const allZero = data.length === 0 || data.every((b) => b.points === 0);
  if (allZero) {
    return (
      <span className="ml-auto text-xs text-muted-foreground">
        No risk signals for this entity in the selected range.
      </span>
    );
  }
  const peak = data.reduce((m, b) => (b.points > m.points ? b : m), data[0]);
  const ariaLabel =
    `Risk history for ${label} over ${range}: peak ${Math.round(peak.points * 10) / 10} ` +
    `at ${fmtBucket(peak.bucket_start_ns)}`;
  return (
    <div className="ml-auto h-12 w-40" role="img" aria-label={ariaLabel}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
          <Line
            type="monotone"
            dataKey="points"
            stroke="currentColor"
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
          <Tooltip content={<TooltipContent />} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
