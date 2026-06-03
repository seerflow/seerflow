import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { SeverityChartPanel } from "./SeverityChartPanel";

vi.mock("@/viz/SeverityStack", () => ({
  SeverityStack: ({ timestamps, info, warn, crit }: {
    timestamps: number[];
    info: number[];
    warn: number[];
    crit: number[];
  }) => (
    <div
      data-testid="severity-stack"
      data-points={timestamps.length}
      data-info={info.length}
      data-warn={warn.length}
      data-crit={crit.length}
    />
  ),
}));

vi.mock("@/components/ui/primitives", () => ({
  Legend: ({ items }: { items: Array<{ label: string; color: string }> }) => (
    <div data-testid="legend">
      {items.map((item) => (
        <span key={item.label} data-testid={`legend-${item.label}`}>
          {item.label}
        </span>
      ))}
    </div>
  ),
  LegendItem: ({ label }: { label: string }) => <span>{label}</span>,
}));

describe("SeverityChartPanel", () => {
  it("renders the chart heading", () => {
    render(<SeverityChartPanel />);
    expect(screen.getByText("Event volume by severity")).toBeInTheDocument();
  });

  it("renders the subtitle", () => {
    render(<SeverityChartPanel />);
    expect(screen.getByText(/last 15 minutes/i)).toBeInTheDocument();
    expect(screen.getByText(/1s resolution/i)).toBeInTheDocument();
  });

  it("renders the SeverityStack chart with demo data", () => {
    render(<SeverityChartPanel />);
    const chart = screen.getByTestId("severity-stack");
    expect(chart).toBeInTheDocument();
    // Should have non-zero data points
    const points = parseInt(chart.getAttribute("data-points") ?? "0");
    expect(points).toBeGreaterThan(0);
  });

  it("renders legend with info/warn/critical labels", () => {
    render(<SeverityChartPanel />);
    expect(screen.getByTestId("legend-info")).toBeInTheDocument();
    expect(screen.getByTestId("legend-warn")).toBeInTheDocument();
    expect(screen.getByTestId("legend-critical")).toBeInTheDocument();
  });

  it("passes equal-length arrays to SeverityStack", () => {
    render(<SeverityChartPanel />);
    const chart = screen.getByTestId("severity-stack");
    const pts = chart.getAttribute("data-points");
    const infoLen = chart.getAttribute("data-info");
    const warnLen = chart.getAttribute("data-warn");
    const critLen = chart.getAttribute("data-crit");
    expect(pts).toBe(infoLen);
    expect(pts).toBe(warnLen);
    expect(pts).toBe(critLen);
  });
});
