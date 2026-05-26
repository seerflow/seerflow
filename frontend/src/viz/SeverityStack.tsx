/**
 * SeverityStack — stacked-area severity chart built on TimeSeries.
 *
 * Shows three bands (info / warn / crit) filled in semantic token colors,
 * plus a total-volume outline in --accent.
 *
 * Data is fed from useStreamingSeries; this component is purely presentational.
 */

import { useMemo } from "react";
import { TimeSeries } from "./TimeSeries";
import type { SeriesConfig } from "./TimeSeries";

export interface SeverityStackProps {
  timestamps: number[];
  info: number[];
  warn: number[];
  crit: number[];
  width?: number;
  height?: number;
  className?: string;
  /**
   * Optional annotation marker timestamp.  When provided a dashed vertical
   * line + dot is drawn at this x-position.
   */
  annotationTs?: number;
  /** Token colors — resolved via resolveTokens; defaults below work for dark theme */
  infoColor?: string;
  warnColor?: string;
  critColor?: string;
  totalColor?: string;
  gridColor?: string;
  axisColor?: string;
}

export function SeverityStack({
  timestamps,
  info,
  warn,
  crit,
  width = 720,
  height = 200,
  className,
  infoColor = "rgba(130,182,220,0.25)",
  warnColor = "rgba(215,160,70,0.55)",
  critColor = "rgba(200,80,60,0.70)",
  totalColor = "oklch(0.745 0.130 283)",
  gridColor = "rgba(255,255,255,0.08)",
  axisColor = "rgba(255,255,255,0.2)",
}: SeverityStackProps) {
  // Compute total for the outline series
  const total = useMemo(
    () => timestamps.map((_, i) => (info[i] ?? 0) + (warn[i] ?? 0) + (crit[i] ?? 0)),
    [timestamps, info, warn, crit],
  );

  const data: [number[], ...number[][]] = useMemo(
    () => [timestamps, info, warn, crit, total],
    [timestamps, info, warn, crit, total],
  );

  const series: SeriesConfig[] = [
    // info band
    { label: "info", stroke: infoColor, fill: infoColor, width: 0 },
    // warn band
    { label: "warn", stroke: warnColor, fill: warnColor, width: 0 },
    // crit band
    { label: "crit", stroke: critColor, fill: critColor, width: 0 },
    // total outline
    { label: "total", stroke: totalColor, fill: "transparent", width: 1.3 },
  ];

  return (
    <TimeSeries
      data={data}
      width={width}
      height={height}
      series={series}
      axes={[
        { stroke: axisColor, grid: { stroke: gridColor, dash: [2, 4] } },
        { stroke: axisColor, grid: { stroke: gridColor, dash: [2, 4] } },
      ]}
      className={className}
    />
  );
}
