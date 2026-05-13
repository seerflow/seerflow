import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { TimeRangeChips } from "./TimeRangeChips";

describe("TimeRangeChips", () => {
  it("renders four chips + disabled Custom chip", () => {
    render(<TimeRangeChips value="1h" onChange={vi.fn()} />);
    for (const label of ["1h", "6h", "24h", "7d", "Custom…"]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "Custom…" })).toBeDisabled();
  });

  it("marks the active chip with aria-pressed", () => {
    render(<TimeRangeChips value="24h" onChange={vi.fn()} />);
    expect(screen.getByRole("button", { name: "24h" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "1h" })).toHaveAttribute("aria-pressed", "false");
  });

  it("calls onChange with the selected range", () => {
    const onChange = vi.fn();
    render(<TimeRangeChips value="1h" onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "6h" }));
    expect(onChange).toHaveBeenCalledWith("6h");
  });

  it("Custom chip is inert", () => {
    const onChange = vi.fn();
    render(<TimeRangeChips value="1h" onChange={onChange} />);
    const custom = screen.getByRole("button", { name: "Custom…" });
    fireEvent.click(custom);
    expect(onChange).not.toHaveBeenCalled();
  });
});
