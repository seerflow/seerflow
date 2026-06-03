/**
 * MiniVolume — 60-second bar strip chart for event volume.
 *
 * Built on TimeSeries (uPlot). Bars are rendered via a uPlot custom `paths`
 * draw function so each bar can be filled with its own color: spikes above the
 * crit / warn thresholds render in the crit / warn token colors while normal
 * bars use the base color (S-329 — was the S-319-spike-bars follow-up).
 *
 * The color-selection logic is factored into the pure `selectBarColor` /
 * `computeBarColors` helpers so it can be unit-tested without canvas pixels.
 *
 * Used in the EventStream header strip.
 */

/* eslint-disable react-refresh/only-export-components -- co-locates the pure
   bar-color selection helpers with the chart component so they can be unit
   tested (S-329); matches the WidgetCatalog precedent. */

import { useMemo } from "react";
import uPlot from "uplot";
import { TimeSeries } from "./TimeSeries";

export interface BarColorOpts {
  normalColor: string;
  warnColor: string;
  critColor: string;
  /** Values >= this render crit. */
  critThreshold: number;
  /** Values >= this (but < crit) render warn. */
  warnThreshold: number;
}

export interface MiniVolumeProps {
  timestamps: number[];
  values: number[];
  width?: number;
  height?: number;
  className?: string;
  normalColor?: string;
  warnColor?: string;
  critColor?: string;
  gridColor?: string;
  /** Explicit crit threshold; derived from the data when omitted. */
  critThreshold?: number;
  /** Explicit warn threshold; derived from the data when omitted. */
  warnThreshold?: number;
}

const DEFAULT_NORMAL = "rgba(81,84,180,0.7)";
const DEFAULT_WARN = "var(--warn)";
const DEFAULT_CRIT = "var(--crit)";
const DEFAULT_GRID = "rgba(255,255,255,0.06)";

/**
 * Pick the fill color for a single bar value given the thresholds. A value
 * at or above `critThreshold` is crit; at or above `warnThreshold` (and below
 * crit) is warn; otherwise normal.
 */
export function selectBarColor(value: number, opts: BarColorOpts): string {
  if (value >= opts.critThreshold) return opts.critColor;
  if (value >= opts.warnThreshold) return opts.warnColor;
  return opts.normalColor;
}

interface DerivableColorOpts {
  normalColor: string;
  warnColor: string;
  critColor: string;
  critThreshold?: number;
  warnThreshold?: number;
}

/**
 * Resolve a per-bar color for every value. When thresholds are not supplied
 * they are derived from the data: crit = max, warn = 75% of max. A flat series
 * (max === min) yields no spikes — every bar is normal.
 */
export function computeBarColors(values: number[], opts: DerivableColorOpts): string[] {
  if (values.length === 0) return [];
  const max = Math.max(...values);
  const min = Math.min(...values);
  const flat = max === min;
  const critThreshold = opts.critThreshold ?? (flat ? Infinity : max);
  const warnThreshold = opts.warnThreshold ?? (flat ? Infinity : min + (max - min) * 0.75);
  const resolved: BarColorOpts = {
    normalColor: opts.normalColor,
    warnColor: opts.warnColor,
    critColor: opts.critColor,
    critThreshold,
    warnThreshold,
  };
  return values.map((v) => selectBarColor(v, resolved));
}

/**
 * Build a uPlot custom paths draw function that fills each bar with the color
 * chosen by `computeBarColors`. Bars are centred on each x position with a
 * width derived from the available pixel spacing.
 */
export function makeBarPaths(values: number[], colorOpts: DerivableColorOpts): uPlot.Series["paths"] {
  return (u, seriesIdx, idx0, idx1) => {
    const colors = computeBarColors(values, colorOpts);
    const ctx = u.ctx;
    const [iMin, iMax] = [idx0, idx1];
    const count = Math.max(1, iMax - iMin + 1);
    const span = u.bbox.width / count;
    const barW = Math.max(1, span * 0.7);
    const zeroY = u.valToPos(0, "y", true);
    ctx.save();
    for (let i = iMin; i <= iMax; i++) {
      const xVal = u.data[0][i];
      const yVal = u.data[seriesIdx][i];
      if (yVal == null) continue;
      const xPos = u.valToPos(xVal as number, "x", true);
      const yPos = u.valToPos(yVal as number, "y", true);
      ctx.fillStyle = colors[i] ?? colorOpts.normalColor;
      ctx.fillRect(xPos - barW / 2, yPos, barW, zeroY - yPos);
    }
    ctx.restore();
    // We draw imperatively; return null so uPlot does not stroke/fill a path.
    return null;
  };
}

export function MiniVolume({
  timestamps,
  values,
  width = 720,
  height = 32,
  className,
  normalColor = DEFAULT_NORMAL,
  warnColor = DEFAULT_WARN,
  critColor = DEFAULT_CRIT,
  gridColor = DEFAULT_GRID,
  critThreshold,
  warnThreshold,
}: MiniVolumeProps) {
  const data: [number[], ...number[][]] = useMemo(
    () => [timestamps, values],
    [timestamps, values],
  );

  // Full uPlot series array (x-axis stub + the volume bars) injected via
  // TimeSeries.extraOpts.series so the custom `paths` draw fn reaches uPlot.
  const seriesOverride = useMemo<uPlot.Series[]>(
    () => [
      {},
      {
        label: "volume",
        stroke: normalColor,
        fill: normalColor,
        width: 1,
        points: { show: false },
        paths: makeBarPaths(values, { normalColor, warnColor, critColor, critThreshold, warnThreshold }),
      },
    ],
    [values, normalColor, warnColor, critColor, critThreshold, warnThreshold],
  );

  return (
    <TimeSeries
      data={data}
      width={width}
      height={height}
      axes={[
        { show: false, grid: { show: false } },
        { show: false, grid: { stroke: gridColor } },
      ]}
      extraOpts={{ padding: [0, 0, 0, 0], series: seriesOverride }}
      className={className}
    />
  );
}
