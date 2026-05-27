/**
 * S-324: SigmaDetailScreen smoke tests.
 */
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { SigmaDetailScreen } from "./SigmaDetailScreen";

describe("SigmaDetailScreen", () => {
  it("renders without crashing", () => {
    expect(() => render(<SigmaDetailScreen />)).not.toThrow();
  });

  it("renders sigma-detail-screen testid", () => {
    render(<SigmaDetailScreen />);
    expect(screen.getByTestId("sigma-detail-screen")).toBeInTheDocument();
  });
});
