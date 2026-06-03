import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { OverviewSkeleton } from "./OverviewSkeleton";

describe("OverviewSkeleton", () => {
  it("renders the skeleton wrapper", () => {
    render(<OverviewSkeleton />);
    expect(screen.getByTestId("overview-skeleton")).toBeInTheDocument();
  });

  it("renders KPI shimmer blocks", () => {
    render(<OverviewSkeleton />);
    const blocks = screen.getAllByTestId("skeleton-block");
    expect(blocks.length).toBeGreaterThan(0);
  });

  it("has animate-pulse class for shimmer effect", () => {
    render(<OverviewSkeleton />);
    const skeleton = screen.getByTestId("overview-skeleton");
    expect(skeleton.querySelector(".animate-pulse")).toBeInTheDocument();
  });
});
