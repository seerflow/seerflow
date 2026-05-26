/**
 * MiniVolume — 60-second bar strip chart for event volume.
 *
 * Built on TimeSeries (uPlot). Single-color fill for now; per-bar spike
 * coloring requires a uPlot paths plugin and is deferred to a follow-up
 * story (S-319-spike-bars).
 *
 * Used in the EventStream header strip.
 */

import { useMemo } from "react";
import { TimeSeries } from "./TimeSeries";
import type { SeriesConfig } from "./TimeSeries";

export interface MiniVolumeProps {
  timestamps: number[];
  values: number[];
  width?: number;
  height?: number;
  className?: string;
  normalColor?: string;
  gridColor?: string;
}

export function MiniVolume({
  timestamps,
  values,
  width = 720,
  height = 32,
  className,
  normalColor = "rgba(81,84,180,0.7)",
  gridColor = "rgba(255,255,255,0.06)",
}: MiniVolumeProps) {
  const data: [number[], ...number[][]] = useMemo(
    () => [timestamps, values],
    [timestamps, values],
  );

  // uPlot bar chart via paths plugin would be ideal; for simplicity use
  // a line fill which visually approximates bars at low height.
  // TODO(S-319-spike-bars): add uPlot paths plugin for true bar rendering
  // + per-bar spike coloring above a computed threshold.
  const series: SeriesConfig[] = [
    {
      label: "volume",
      stroke: normalColor,
      fill: normalColor,
      width: 1,
      spanGaps: true,
    },
  ];

  return (
    <TimeSeries
      data={data}
      width={width}
      height={height}
      series={series}
      axes={[
        { show: false, grid: { show: false } },
        { show: false, grid: { stroke: gridColor } },
      ]}
      extraOpts={{ padding: [0, 0, 0, 0] }}
      className={className}
    />
  );
}
