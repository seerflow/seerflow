/**
 * TimeSeries — thin React wrapper around a uPlot instance.
 *
 * Key design constraints:
 * - The uPlot instance is created ONCE on mount and stored in a ref.
 * - Data updates go through `u.setData()` imperatively — no React state,
 *   no re-render, no re-create on every tick.
 * - Theme tokens are applied at construction time; re-theming is handled
 *   externally via `subscribeToThemeChanges` (not in scope of this wrapper).
 */

import { useEffect, useRef } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";

// --------------------------------------------------------------------------
// Types
// --------------------------------------------------------------------------

export interface SeriesConfig {
  label?: string;
  stroke?: string;
  fill?: string;
  width?: number;
  dash?: number[];
  points?: uPlot.Series["points"];
  spanGaps?: boolean;
}

export interface TimeSeriesProps {
  /**
   * Aligned data array: [timestamps, series0, series1, …].
   * When this reference changes, `u.setData()` is called imperatively.
   */
  data: [number[], ...number[][]];
  width: number;
  height: number;
  /** Series configs (excluding the implicit x-axis timestamps series) */
  series?: SeriesConfig[];
  /** Additional uPlot axes config */
  axes?: uPlot.Axis[];
  /** Additional uPlot scales config */
  scales?: Record<string, uPlot.Scale>;
  className?: string;
  /** Extra uPlot options (merged last, may override above) */
  extraOpts?: Partial<uPlot.Options>;
}

// --------------------------------------------------------------------------
// Component
// --------------------------------------------------------------------------

export function TimeSeries({
  data,
  width,
  height,
  series = [],
  axes,
  scales,
  className,
  extraOpts,
}: TimeSeriesProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const uplotRef = useRef<uPlot | null>(null);
  // Track the last data reference to avoid calling setData with same ref
  const dataRef = useRef<[number[], ...number[][]] | null>(null);

  // ── Create instance on mount ─────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return;

    const opts: uPlot.Options = {
      width,
      height,
      series: [
        // Implicit x-axis series (timestamps)
        {},
        // User-provided series
        ...series.map((s) => ({
          label: s.label,
          stroke: s.stroke,
          fill: s.fill,
          width: s.width ?? 1.5,
          dash: s.dash,
          points: s.points ?? { show: false },
          spanGaps: s.spanGaps ?? false,
        })),
      ],
      axes: axes ?? [
        { stroke: "rgba(255,255,255,0.2)", grid: { stroke: "rgba(255,255,255,0.08)", dash: [2, 4] } },
        { stroke: "rgba(255,255,255,0.2)", grid: { stroke: "rgba(255,255,255,0.08)", dash: [2, 4] } },
      ],
      scales: scales,
      cursor: { show: false },
      legend: { show: false },
      ...extraOpts,
    };

    const u = new uPlot(opts, data, containerRef.current);
    uplotRef.current = u;
    dataRef.current = data;

    return () => {
      u.destroy();
      uplotRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // intentionally empty: create once, destroy on unmount

  // ── Imperative data updates ──────────────────────────────────────────────
  useEffect(() => {
    const u = uplotRef.current;
    if (!u) return;
    if (data === dataRef.current) return; // same reference, nothing changed
    dataRef.current = data;
    u.setData(data, false);
  }, [data]);

  return <div ref={containerRef} className={className} />;
}
