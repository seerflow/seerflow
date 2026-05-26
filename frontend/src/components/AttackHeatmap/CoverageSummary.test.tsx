import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { CoverageSummary } from "./CoverageSummary";

describe("CoverageSummary", () => {
  it("renders detectedTactics stat", () => {
    render(
      <CoverageSummary
        detectedTactics={7}
        criticalHeat={2}
        ruleCoveragePct={74}
        mlOnlyDetections={11}
      />,
    );
    expect(screen.getByText(/detected tactics/i)).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
  });

  it("renders criticalHeat stat", () => {
    render(
      <CoverageSummary
        detectedTactics={7}
        criticalHeat={2}
        ruleCoveragePct={74}
        mlOnlyDetections={11}
      />,
    );
    expect(screen.getByText(/critical heat/i)).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("renders ruleCoveragePct stat with % suffix", () => {
    render(
      <CoverageSummary
        detectedTactics={7}
        criticalHeat={2}
        ruleCoveragePct={74}
        mlOnlyDetections={11}
      />,
    );
    expect(screen.getByText(/rule coverage/i)).toBeInTheDocument();
    expect(screen.getByText("74%")).toBeInTheDocument();
  });

  it("renders mlOnlyDetections stat", () => {
    render(
      <CoverageSummary
        detectedTactics={7}
        criticalHeat={2}
        ruleCoveragePct={74}
        mlOnlyDetections={11}
      />,
    );
    expect(screen.getByText(/ml-only detections/i)).toBeInTheDocument();
    expect(screen.getByText("11")).toBeInTheDocument();
  });

  it("renders all 4 stats in a grid container", () => {
    const { container } = render(
      <CoverageSummary
        detectedTactics={7}
        criticalHeat={2}
        ruleCoveragePct={74}
        mlOnlyDetections={11}
      />,
    );
    const summary = container.querySelector('[data-testid="coverage-summary"]');
    expect(summary).not.toBeNull();
    // All 4 stat labels present
    expect(screen.getByText(/detected tactics/i)).toBeInTheDocument();
    expect(screen.getByText(/critical heat/i)).toBeInTheDocument();
    expect(screen.getByText(/rule coverage/i)).toBeInTheDocument();
    expect(screen.getByText(/ml-only detections/i)).toBeInTheDocument();
  });

  it("renders zero state without errors", () => {
    render(
      <CoverageSummary
        detectedTactics={0}
        criticalHeat={0}
        ruleCoveragePct={0}
        mlOnlyDetections={0}
      />,
    );
    expect(screen.getByText("0%")).toBeInTheDocument();
  });
});
