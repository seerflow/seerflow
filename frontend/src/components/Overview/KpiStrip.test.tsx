import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { KpiStrip } from "./KpiStrip";

vi.mock("@/viz/Sparkline", () => ({
  Sparkline: ({ data }: { data: unknown[] }) => (
    <div data-testid="sparkline" data-points={data.length} />
  ),
}));

describe("KpiStrip", () => {
  const defaultProps = {
    eventsPerSec: 12847,
    activeEntities: 3294,
    openAlerts: 17,
    meanLatencyMs: 38,
  };

  it("renders 4 KPI cards", () => {
    render(<KpiStrip {...defaultProps} />);
    expect(screen.getByTestId("kpi-events-per-sec")).toBeInTheDocument();
    expect(screen.getByTestId("kpi-active-entities")).toBeInTheDocument();
    expect(screen.getByTestId("kpi-open-alerts")).toBeInTheDocument();
    expect(screen.getByTestId("kpi-mean-latency")).toBeInTheDocument();
  });

  it("renders formatted events/sec value", () => {
    render(<KpiStrip {...defaultProps} />);
    expect(screen.getByTestId("kpi-events-per-sec")).toHaveTextContent("12,847");
  });

  it("renders active entities value", () => {
    render(<KpiStrip {...defaultProps} />);
    expect(screen.getByTestId("kpi-active-entities")).toHaveTextContent("3,294");
  });

  it("renders open alerts value", () => {
    render(<KpiStrip {...defaultProps} />);
    expect(screen.getByTestId("kpi-open-alerts")).toHaveTextContent("17");
  });

  it("renders mean latency with ms suffix", () => {
    render(<KpiStrip {...defaultProps} />);
    expect(screen.getByTestId("kpi-mean-latency")).toHaveTextContent("38ms");
  });

  it("renders 4 sparklines", () => {
    render(<KpiStrip {...defaultProps} />);
    expect(screen.getAllByTestId("sparkline")).toHaveLength(4);
  });

  it("renders mono labels for each KPI", () => {
    render(<KpiStrip {...defaultProps} />);
    expect(screen.getByText(/events \/ sec/i)).toBeInTheDocument();
    expect(screen.getByText(/active entities/i)).toBeInTheDocument();
    expect(screen.getByText(/open alerts/i)).toBeInTheDocument();
    expect(screen.getByText(/mean latency/i)).toBeInTheDocument();
  });

  it("renders positive delta with accent color class", () => {
    render(<KpiStrip {...defaultProps} eventsPerSecDelta="+4.2%" />);
    const delta = screen.getByTestId("kpi-events-per-sec-delta");
    expect(delta).toHaveTextContent("+4.2%");
    expect(delta).not.toHaveStyle({ color: "var(--crit)" });
  });

  it("renders negative delta with crit color class", () => {
    render(<KpiStrip {...defaultProps} activeEntitiesDelta="-1.8%" />);
    const delta = screen.getByTestId("kpi-active-entities-delta");
    expect(delta).toHaveTextContent("-1.8%");
  });
});
