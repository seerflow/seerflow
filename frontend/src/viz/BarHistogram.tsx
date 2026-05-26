/**
 * BarHistogram — recharts BarChart wrapper for rule hit trends.
 *
 * Restyled to token colors. Bars colored by threshold: above → spikeColor, below → normalColor.
 */

import {
  BarChart,
  Bar,
  Cell,
  ResponsiveContainer,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";

export interface BarHistogramDataPoint {
  t: number;
  v: number;
}

export interface BarHistogramProps {
  data: BarHistogramDataPoint[];
  height?: number;
  className?: string;
  threshold?: number;
  normalColor?: string;
  spikeColor?: string;
  showTooltip?: boolean;
}

export function BarHistogram({
  data,
  height = 64,
  className,
  threshold,
  normalColor = "var(--accent)",
  spikeColor = "var(--warn)",
  showTooltip = false,
}: BarHistogramProps) {
  const chartData = data.map((d) => ({ t: d.t, v: d.v }));

  // Compute effective threshold
  const effectiveThreshold = threshold != null
    ? threshold
    : data.length > 0 ? Math.max(...data.map((d) => d.v)) * 0.75 : Infinity;

  return (
    <div className={className}>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart
          data={chartData}
          margin={{ top: 0, right: 0, bottom: 0, left: 0 }}
          barCategoryGap="10%"
        >
          <CartesianGrid
            vertical={false}
            stroke="var(--line)"
            strokeDasharray="2 4"
            opacity={0.6}
          />
          <XAxis dataKey="t" hide />
          <YAxis hide domain={[0, "auto"]} />
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
          <Bar
            dataKey="v"
            isAnimationActive={false}
          >
            {chartData.map((entry, index) => (
              <Cell
                key={`cell-${index}`}
                fill={entry.v > effectiveThreshold ? spikeColor : normalColor}
                opacity={0.75}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
