import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SummaryBadges } from "./SummaryBadges";

describe("SummaryBadges", () => {
  it("renders counts", () => {
    render(<SummaryBadges counts={{total: 4, critical: 1, high: 1, medium: 1, low: 1}} status="open" />);
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByText(/Critical/i)).toBeInTheDocument();
  });
});
