/**
 * OverviewScreen live-data wiring tests (S-328 AC1 / AC5).
 *
 * Drives the live (non-demo) branch by marking the pipeline online, then
 * asserts the KPI strip reflects the status-store `activeEntities` /
 * `meanLatencyMs` (live when present, demo fallback when at defaults). The
 * heavy child panels are mocked to keep the smoke fast.
 */
import { render, screen } from "@testing-library/react";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import * as wsBus from "@/lib/wsBus";
import { useStatusStore } from "@/stores/status";
import { useAlertStore } from "@/stores/alerts";
import { DEMO_ACTIVE_ENTITIES, DEMO_MEAN_LATENCY_MS } from "@/lib/liveStats";

// Mock the heavy panels — we only assert on the KPI strip values here.
vi.mock("@/components/Overview/SeverityChartPanel", () => ({
  SeverityChartPanel: () => <div data-testid="severity-chart-panel" />,
}));
vi.mock("@/components/Overview/RecentAlertsList", () => ({
  RecentAlertsList: () => <div data-testid="recent-alerts-list" />,
}));
vi.mock("@/components/Overview/TopRiskEntities", () => ({
  TopRiskEntities: () => <div data-testid="top-risk-entities" />,
}));
vi.mock("@/components/Overview/OverviewSkeleton", () => ({
  OverviewSkeleton: () => <div data-testid="overview-skeleton" />,
}));

import { OverviewScreen } from "./OverviewScreen";

function resetStores() {
  wsBus._clearAllForTests();
  useStatusStore.setState({
    pipelineOnline: false,
    uptimeLabel: "—",
    evPerSec: 0,
    activeEntities: 0,
    meanLatencyMs: 0,
  });
  useStatusStore.getState()._resubscribe();
  useAlertStore.setState({ alerts: [] });
}

describe("OverviewScreen live KPI wiring (S-328)", () => {
  beforeEach(resetStores);
  afterEach(() => wsBus._clearAllForTests());

  it("shows live activeEntities / meanLatencyMs in the non-demo branch", () => {
    useStatusStore.setState({
      pipelineOnline: true,
      activeEntities: 4_812,
      meanLatencyMs: 54,
    });
    render(<OverviewScreen />);
    expect(screen.getByTestId("kpi-active-entities")).toHaveTextContent("4,812");
    expect(screen.getByTestId("kpi-mean-latency")).toHaveTextContent("54ms");
  });

  it("falls back to demo KPI numbers when online but metrics are at defaults", () => {
    useStatusStore.setState({ pipelineOnline: true, activeEntities: 0, meanLatencyMs: 0 });
    render(<OverviewScreen />);
    expect(screen.getByTestId("kpi-active-entities")).toHaveTextContent(
      DEMO_ACTIVE_ENTITIES.toLocaleString(),
    );
    expect(screen.getByTestId("kpi-mean-latency")).toHaveTextContent(
      `${DEMO_MEAN_LATENCY_MS}ms`,
    );
  });

  it("renders the demo skeleton when offline with no alerts (unchanged demo mode)", () => {
    render(<OverviewScreen />);
    expect(screen.getByTestId("overview-skeleton")).toBeInTheDocument();
  });
});
