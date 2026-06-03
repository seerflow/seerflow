import React from "react";
import { Stat } from "@/components/ui/primitives";
import { Sparkline } from "@/viz/Sparkline";
import type { SparklineDataPoint } from "@/viz/Sparkline";

export interface KpiStripProps {
  eventsPerSec: number;
  activeEntities: number;
  openAlerts: number;
  meanLatencyMs: number;
  eventsPerSecDelta?: string;
  activeEntitiesDelta?: string;
  openAlertsDelta?: string;
  meanLatencyDelta?: string;
}

/** Generate a deterministic sparkline series for demo mode. */
function demoSpark(kind: "up" | "down" | "flat"): SparklineDataPoint[] {
  const raw =
    kind === "up"   ? [3, 4, 3, 5, 4, 6, 5, 7, 6, 8] :
    kind === "down" ? [8, 7, 7, 6, 6, 5, 5, 4, 4, 3] :
                     [5, 6, 5, 4, 6, 5, 6, 5, 6, 5];
  return raw.map((v, i) => ({ t: i, v }));
}

const SPARK_UP   = demoSpark("up");
const SPARK_FLAT = demoSpark("flat");
const SPARK_DOWN = demoSpark("down");

function isNegativeDelta(delta: string | undefined): boolean {
  return delta !== undefined && delta.startsWith("-");
}

interface KpiCardProps {
  testId: string;
  label: string;
  value: React.ReactNode;
  delta?: string;
  sparkData: SparklineDataPoint[];
}

const KpiCard: React.FC<KpiCardProps> = ({ testId, label, value, delta, sparkData }) => {
  const negative = isNegativeDelta(delta);
  return (
    <div
      data-testid={testId}
      className="flex flex-col gap-0"
      style={{ padding: "18px 20px 16px" }}
    >
      <Stat
        label={label}
        value={value}
        className="gap-1"
      >
        <div className="flex items-center gap-2 mt-1">
          {delta !== undefined && (
            <span
              data-testid={`${testId}-delta`}
              className="sf-mono sf-tnum text-[11px]"
              style={{ color: negative ? "var(--crit)" : "var(--accent)" }}
            >
              {delta}
            </span>
          )}
          <Sparkline data={sparkData} height={16} color="var(--text-3)" />
        </div>
      </Stat>
    </div>
  );
};

/**
 * 4-up KPI strip for the Overview screen.
 * Each card: mono label + large tnum value + delta + sparkline.
 */
export const KpiStrip: React.FC<KpiStripProps> = ({
  eventsPerSec,
  activeEntities,
  openAlerts,
  meanLatencyMs,
  eventsPerSecDelta,
  activeEntitiesDelta,
  openAlertsDelta,
  meanLatencyDelta,
}) => (
  <div
    style={{
      display: "grid",
      gridTemplateColumns: "repeat(4, 1fr)",
      borderBottom: "1px solid var(--line)",
    }}
  >
    <div style={{ borderRight: "1px solid var(--line)" }}>
      <KpiCard
        testId="kpi-events-per-sec"
        label="events / sec"
        value={eventsPerSec.toLocaleString()}
        delta={eventsPerSecDelta}
        sparkData={SPARK_UP}
      />
    </div>
    <div style={{ borderRight: "1px solid var(--line)" }}>
      <KpiCard
        testId="kpi-active-entities"
        label="active entities"
        value={activeEntities.toLocaleString()}
        delta={activeEntitiesDelta}
        sparkData={SPARK_FLAT}
      />
    </div>
    <div style={{ borderRight: "1px solid var(--line)" }}>
      <KpiCard
        testId="kpi-open-alerts"
        label="open alerts"
        value={openAlerts.toLocaleString()}
        delta={openAlertsDelta}
        sparkData={SPARK_UP}
      />
    </div>
    <KpiCard
      testId="kpi-mean-latency"
      label="mean latency"
      value={`${meanLatencyMs}ms`}
      delta={meanLatencyDelta}
      sparkData={SPARK_DOWN}
    />
  </div>
);
