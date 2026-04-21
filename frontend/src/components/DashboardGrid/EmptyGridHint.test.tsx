import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { EmptyGridHint } from "./EmptyGridHint";

describe("EmptyGridHint", () => {
  it("renders the recovery copy and a reset affordance", () => {
    render(<EmptyGridHint />);
    expect(screen.getByText(/Your dashboard is empty/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reset layout/i })).toBeInTheDocument();
  });
});
