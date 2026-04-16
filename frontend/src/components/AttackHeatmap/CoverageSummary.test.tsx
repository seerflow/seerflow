import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { CoverageSummary } from "./CoverageSummary";

describe("CoverageSummary", () => {
  it("renders coverage counts", () => {
    render(
      <CoverageSummary
        totalTechniques={200}
        coveredCount={45}
        detectedCount={12}
        totalRules={60}
        totalAlerts={150}
        windowSince="2026-03-16T00:00:00+00:00"
        windowUntil="2026-04-15T00:00:00+00:00"
      />,
    );
    expect(screen.getByText(/45/)).toBeInTheDocument();
    expect(screen.getByText(/200/)).toBeInTheDocument();
    expect(screen.getByText(/12/)).toBeInTheDocument();
  });

  it("renders zero state", () => {
    render(
      <CoverageSummary
        totalTechniques={200}
        coveredCount={0}
        detectedCount={0}
        totalRules={0}
        totalAlerts={0}
        windowSince="2026-03-16T00:00:00+00:00"
        windowUntil="2026-04-15T00:00:00+00:00"
      />,
    );
    const zeros = screen.getAllByText(/0/);
    expect(zeros.length).toBeGreaterThan(0);
  });
});
