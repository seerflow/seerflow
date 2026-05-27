import React, { useMemo } from "react";
import { SeverityStack } from "@/viz/SeverityStack";
import { Legend } from "@/components/ui/primitives";
import type { LegendItemData } from "@/components/ui/primitives";

/**
 * Generate deterministic demo data for the SeverityStack chart.
 * Uses the same sinusoidal formula from dashboard.jsx StackChart().
 * Returns 60 data points for the 15-minute window.
 */
function buildDemoData(N = 60): {
  timestamps: number[];
  info: number[];
  warn: number[];
  crit: number[];
} {
  const timestamps: number[] = [];
  const info: number[] = [];
  const warn: number[] = [];
  const crit: number[] = [];

  const nowSec = Math.floor(Date.now() / 1000);
  for (let i = 0; i < N; i++) {
    const t = i / N;
    const infoVal = 60 + 28 * Math.sin(t * 6.2) + 14 * Math.sin(t * 13.1 + 1);
    const warnVal = 12 + 8 * Math.sin(t * 8.4 + 0.4) + (i > 38 && i < 50 ? 16 : 0);
    const critVal = (i > 42 && i < 48 ? 8 + (i - 42) * 1.5 : 0) + (i > 52 ? 3 : 0);

    timestamps.push(nowSec - (N - i));
    info.push(Math.max(0, infoVal));
    warn.push(Math.max(0, warnVal));
    crit.push(Math.max(0, critVal));
  }

  return { timestamps, info, warn, crit };
}

const LEGEND_ITEMS: LegendItemData[] = [
  { label: "info",     color: "var(--text-3)" },
  { label: "warn",     color: "var(--warn)" },
  { label: "critical", color: "var(--crit)" },
];

export interface SeverityChartPanelProps {
  /** Override with live data when available; defaults to deterministic demo data. */
  timestamps?: number[];
  info?: number[];
  warn?: number[];
  crit?: number[];
  height?: number;
}

/**
 * "Event volume by severity" chart panel.
 * Wraps SeverityStack with the title, subtitle, and legend from the mockup.
 */
export const SeverityChartPanel: React.FC<SeverityChartPanelProps> = ({
  timestamps: tsProp,
  info: infoProp,
  warn: warnProp,
  crit: critProp,
  height = 180,
}) => {
  const demo = useMemo(() => buildDemoData(), []);

  const timestamps = tsProp ?? demo.timestamps;
  const info       = infoProp ?? demo.info;
  const warn       = warnProp ?? demo.warn;
  const crit       = critProp ?? demo.crit;

  return (
    <div style={{ padding: "20px 24px", borderBottom: "1px solid var(--line)" }}>
      {/* Header row */}
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: 16,
        }}
      >
        <div>
          <div style={{ fontSize: 15, fontWeight: 600, letterSpacing: "-0.01em" }}>
            Event volume by severity
          </div>
          <div className="sf-mono" style={{ fontSize: 10.5, color: "var(--text-3)", marginTop: 2 }}>
            last 15 minutes · 1s resolution
          </div>
        </div>
        <Legend items={LEGEND_ITEMS} />
      </div>

      {/* Chart */}
      <SeverityStack
        timestamps={timestamps}
        info={info}
        warn={warn}
        crit={crit}
        height={height}
        width={720}
      />
    </div>
  );
};
