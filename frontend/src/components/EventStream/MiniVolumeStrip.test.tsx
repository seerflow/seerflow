import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MiniVolumeStrip } from "./MiniVolumeStrip";

// MiniVolume uses uPlot which doesn't work in jsdom
vi.mock("@/viz/MiniVolume", () => ({
  MiniVolume: ({ timestamps, values }: { timestamps: number[]; values: number[] }) => (
    <div data-testid="mini-volume-chart" data-ts-len={timestamps.length} data-val-len={values.length} />
  ),
}));

describe("MiniVolumeStrip", () => {
  const baseProps = {
    timestamps: [1, 2, 3],
    values: [10, 20, 30],
    critCount: 2,
    warnCount: 5,
  };

  it("shows volume · 60s window label", () => {
    render(<MiniVolumeStrip {...baseProps} />);
    expect(screen.getByText(/volume · 60s window/i)).toBeInTheDocument();
  });

  it("shows crit count", () => {
    render(<MiniVolumeStrip {...baseProps} />);
    expect(screen.getByText(/2 crit/i)).toBeInTheDocument();
  });

  it("shows warn count", () => {
    render(<MiniVolumeStrip {...baseProps} />);
    expect(screen.getByText(/5 warn/i)).toBeInTheDocument();
  });

  it("renders the MiniVolume chart component", () => {
    render(<MiniVolumeStrip {...baseProps} />);
    expect(screen.getByTestId("mini-volume-chart")).toBeInTheDocument();
  });

  it("passes timestamps and values to MiniVolume", () => {
    render(<MiniVolumeStrip {...baseProps} />);
    const chart = screen.getByTestId("mini-volume-chart");
    expect(chart.getAttribute("data-ts-len")).toBe("3");
    expect(chart.getAttribute("data-val-len")).toBe("3");
  });

  it("shows zero counts without crashing", () => {
    render(<MiniVolumeStrip {...baseProps} critCount={0} warnCount={0} />);
    expect(screen.getByText(/0 crit/i)).toBeInTheDocument();
    expect(screen.getByText(/0 warn/i)).toBeInTheDocument();
  });
});
