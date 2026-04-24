import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { RiskSparkline } from "./RiskSparkline";

const zeros = Array.from({ length: 60 }, (_, i) => ({
  bucket_start_ns: String(i * 60_000_000_000),
  points: 0,
  alert_count: 0,
  top_rule_name: "",
}));

describe("RiskSparkline", () => {
  it("renders loading skeleton while loading", () => {
    render(
      <RiskSparkline data={[]} loading={true} error={null} range="1h" label="alice" />,
    );
    expect(screen.getByRole("status")).toHaveAttribute(
      "aria-label",
      "Loading risk history",
    );
  });

  it("renders empty-state copy when all points are zero", () => {
    render(
      <RiskSparkline
        data={zeros}
        loading={false}
        error={null}
        range="1h"
        label="alice"
      />,
    );
    expect(
      screen.getByText(/No risk signals for this entity/i),
    ).toBeInTheDocument();
  });

  it("renders error copy on error", () => {
    render(
      <RiskSparkline
        data={[]}
        loading={false}
        error="boom"
        range="1h"
        label="alice"
      />,
    );
    expect(screen.getByText(/Risk history unavailable/i)).toBeInTheDocument();
  });

  it("renders an accessible SVG line when data is non-zero", () => {
    const data = zeros.map((b, i) => (i === 5 ? { ...b, points: 1.0 } : b));
    render(
      <RiskSparkline
        data={data}
        loading={false}
        error={null}
        range="1h"
        label="alice"
      />,
    );
    const svg = screen.getByRole("img");
    expect(svg.getAttribute("aria-label")).toContain("alice");
  });
});
