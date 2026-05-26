import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { FilterChip, FilterRow } from "./FilterChip";

describe("FilterChip", () => {
  it("renders the label", () => {
    render(<FilterChip label="All" active={false} />);
    expect(screen.getByText("All")).toBeTruthy();
  });

  it("active chip has accent border class", () => {
    const { container } = render(<FilterChip label="Force" active={true} />);
    const cls = container.firstElementChild?.className ?? "";
    expect(cls).toMatch(/border-accent|text-accent/);
  });

  it("inactive chip does not have accent classes", () => {
    const { container } = render(<FilterChip label="Force" active={false} />);
    const cls = container.firstElementChild?.className ?? "";
    // Should use muted or text-3 styling
    expect(cls).toMatch(/text-3|mute|text-text-3/);
  });

  it("calls onClick when clicked", async () => {
    const onClick = vi.fn();
    render(<FilterChip label="Force" active={false} onClick={onClick} />);
    await userEvent.click(screen.getByText("Force"));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("has sf-mono class", () => {
    const { container } = render(<FilterChip label="x" active={false} />);
    expect(container.firstElementChild?.className).toContain("sf-mono");
  });
});

describe("FilterRow", () => {
  it("renders child FilterChips", () => {
    const { container } = render(
      <FilterRow>
        <FilterChip label="All" active={true} />
        <FilterChip label="Force" active={false} />
      </FilterRow>
    );
    expect(container.textContent).toContain("All");
    expect(container.textContent).toContain("Force");
  });
});
