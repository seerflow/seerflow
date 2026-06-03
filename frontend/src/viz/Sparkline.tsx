/**
 * Sparkline — recharts LineChart wrapper for low-frequency KPI deltas.
 *
 * Restyled to token colors: axis/grid --line dashed, series --accent/--warn/--crit.
 * Mono tick labels. Uses ResponsiveContainer.
 */

import {
  LineChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  YAxis,
  XAxis,
} from "recharts";

export interface SparklineDataPoint {
  t: number;
  v: number;
}

export interface SparklineProps {
  data: SparklineDataPoint[];
  color?: string;
  width?: number;
  height?: number;
  className?: string;
  /** Show tooltip on hover */
  showTooltip?: boolean;
}

export function Sparkline({
  data,
  color = "var(--accent)",
  width,
  height = 16,
  className,
  showTooltip = false,
}: SparklineProps) {
  const chartData = data.map((d) => ({ t: d.t, v: d.v }));

  const inner = (
    <LineChart data={chartData} margin={{ top: 1, right: 0, bottom: 1, left: 0 }}>
      <XAxis dataKey="t" hide />
      <YAxis hide domain={["auto", "auto"]} />
      {showTooltip && (
        <Tooltip
          contentStyle={{
            background: "var(--surface)",
            border: "1px solid var(--line)",
            fontSize: 11,
            fontFamily: "var(--font-mono)",
            color: "var(--text-2)",
          }}
        />
      )}
      <Line
        type="monotone"
        dataKey="v"
        stroke={color}
        strokeWidth={1}
        dot={false}
        isAnimationActive={false}
      />
    </LineChart>
  );

  const content = width ? (
    <div className={className} style={{ width, height }}>
      <ResponsiveContainer width="100%" height={height}>
        {inner}
      </ResponsiveContainer>
    </div>
  ) : (
    <div className={className} style={{ height }}>
      <ResponsiveContainer width="100%" height={height}>
        {inner}
      </ResponsiveContainer>
    </div>
  );

  return content;
}
