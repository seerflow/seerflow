/**
 * S-320: Overview screen — 2-column redesign per spec §9.1 / DashOverview mockup.
 *
 * Layout: 1.7fr / 1fr grid.
 * Left:  KPI strip (4-up) + SeverityChartPanel + RecentAlertsList.
 * Right: TopRiskEntities.
 *
 * Demo mode: hard-coded deterministic data when pipeline is offline + no alerts.
 * Loading state: <OverviewSkeleton /> when status=connecting + no alerts yet.
 */
import React, { useMemo } from "react";

import { useAlertStore } from "@/stores/alerts";
import { useStatusStore } from "@/stores/status";

import { KpiStrip } from "@/components/Overview/KpiStrip";
import { SeverityChartPanel } from "@/components/Overview/SeverityChartPanel";
import { RecentAlertsList } from "@/components/Overview/RecentAlertsList";
import { TopRiskEntities } from "@/components/Overview/TopRiskEntities";
import { OverviewSkeleton } from "@/components/Overview/OverviewSkeleton";
import type { RiskEntity } from "@/components/Overview/TopRiskEntities";

// ─── Demo / placeholder data ─────────────────────────────────────────────────

const DEMO_KPI = {
  eventsPerSec: 12_847,
  activeEntities: 3_294,
  openAlerts: 17,
  meanLatencyMs: 38,
  eventsPerSecDelta: "+4.3%",
  activeEntitiesDelta: "+1.1%",
  openAlertsDelta: "+2.0%",
  meanLatencyDelta: "-6.1%",
};

const DEMO_ENTITIES: RiskEntity[] = [
  {
    id: "e1",
    name: "root@10.0.1.42",
    kind: "ip",
    risk: 0.94,
    eventCount: 14_230,
    alertCount: 7,
  },
  {
    id: "e2",
    name: "svc-deploy",
    kind: "service",
    risk: 0.87,
    eventCount: 8_971,
    alertCount: 4,
  },
  {
    id: "e3",
    name: "web-04",
    kind: "host",
    risk: 0.76,
    eventCount: 5_120,
    alertCount: 3,
  },
  {
    id: "e4",
    name: "win-jumphost",
    kind: "host",
    risk: 0.64,
    eventCount: 3_892,
    alertCount: 2,
  },
  {
    id: "e5",
    name: "admin@aws",
    kind: "user",
    risk: 0.52,
    eventCount: 2_440,
    alertCount: 1,
  },
  {
    id: "e6",
    name: "203.0.113.41",
    kind: "ip",
    risk: 0.41,
    eventCount: 1_803,
    alertCount: 1,
  },
  {
    id: "e7",
    name: "jenkins-agent-7",
    kind: "process",
    risk: 0.28,
    eventCount: 970,
    alertCount: 0,
  },
];

// ─── OverviewScreen ───────────────────────────────────────────────────────────

export const OverviewScreen: React.FC = () => {
  const alerts = useAlertStore((s) => s.alerts);
  const pipelineOnline = useStatusStore((s) => s.pipelineOnline);
  const evPerSec = useStatusStore((s) => s.evPerSec);

  // Show skeleton while the WS has not yet opened and no cached alerts exist.
  // `pipelineOnline` is set true by the status store on the first WS open event
  // so this transitions to false as soon as the connection is established.
  const isLoading = !pipelineOnline && alerts.length === 0;
  const isDemoMode = !pipelineOnline && alerts.length === 0;

  const recentAlerts = useMemo(() => alerts.slice(0, 5), [alerts]);

  const kpiProps = isDemoMode
    ? DEMO_KPI
    : {
        eventsPerSec: evPerSec,
        activeEntities: 0,
        openAlerts: alerts.length,
        meanLatencyMs: 0,
      };

  if (isLoading) {
    return <OverviewSkeleton />;
  }

  return (
    <div
      data-testid="overview-screen"
      style={{
        display: "grid",
        gridTemplateColumns: "1.7fr 1fr",
        height: "100%",
        overflow: "hidden",
      }}
    >
      {/* ── Left column ─────────────────────────────────── */}
      <div
        data-testid="overview-left"
        style={{
          borderRight: "1px solid var(--line)",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        <KpiStrip {...kpiProps} />
        <SeverityChartPanel />
        <RecentAlertsList
          alerts={recentAlerts}
          totalCount={alerts.length > 0 ? alerts.length : undefined}
        />
      </div>

      {/* ── Right column ────────────────────────────────── */}
      <div
        data-testid="overview-right"
        style={{
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        <TopRiskEntities entities={isDemoMode ? DEMO_ENTITIES : []} />
      </div>
    </div>
  );
};
