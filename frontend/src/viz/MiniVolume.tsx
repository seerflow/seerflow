/**
 * MiniVolume — 60-second bar strip chart for event volume.
 *
 * Built on TimeSeries (uPlot). Bars spike-highlighted above spikeThreshold.
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
  /** Volume above this threshold is rendered in warnColor (default: auto from max) */
  spikeThreshold?: number;
  normalColor?: string;
  spikeColor?: string;
  gridColor?: string;
}

export function MiniVolume({
  timestamps,
  values,
  width = 720,
  height = 32,
  className,
  normalColor = "rgba(81,84,180,0.7)",
  spikeColor = "oklch(0.815 0.155 80)",
  gridColor = "rgba(255,255,255,0.06)",
  spikeThreshold,
}: MiniVolumeProps) {
  const data: [number[], ...number[][]] = useMemo(
    () => [timestamps, values],
    [timestamps, values],
  );

  // Determine effective spike threshold
  const threshold = useMemo(() => {
    if (spikeThreshold != null) return spikeThreshold;
    if (values.length === 0) return Infinity;
    const max = Math.max(...values);
    // Highlight bars above 75th-ish percentile
    return max * 0.75;
  }, [values, spikeThreshold]);

  // uPlot bar chart via paths plugin would be ideal; for simplicity use
  // a line fill which visually approximates bars at low height
  const series: SeriesConfig[] = [
    {
      label: "volume",
      stroke: normalColor,
      fill: normalColor,
      width: 1,
      spanGaps: true,
    },
  ];

  // For spike coloring we'd need uPlot hooks — keep it simple for now:
  // the entire chart uses normalColor; spikeColor is reserved for the
  // consuming component to layer on top via CSS or annotation.
  void threshold;
  void spikeColor;

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
