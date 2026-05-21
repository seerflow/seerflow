import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SeverityChip } from "./SeverityChip";

describe("SeverityChip", () => {
  it("renders a button whose accessible name is the verbatim label", () => {
    render(<SeverityChip label="Critical" active={false} onToggle={() => {}} />);
    const chip = screen.getByRole("button", { name: "Critical" });
    expect(chip).toBeInTheDocument();
    expect(chip).toHaveTextContent("Critical");
  });

  it("does not transform the label text in the DOM (capitalize is CSS only)", () => {
    render(<SeverityChip label="critical" active={false} onToggle={() => {}} />);
    expect(
      screen.getByRole("button", { name: "critical" }),
    ).toHaveTextContent("critical");
  });

  it("reflects the active prop via aria-pressed", () => {
    const { rerender } = render(
      <SeverityChip label="High" active={false} onToggle={() => {}} />,
    );
    expect(screen.getByRole("button", { name: "High" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    rerender(<SeverityChip label="High" active onToggle={() => {}} />);
    expect(screen.getByRole("button", { name: "High" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("applies the active token class only when active", () => {
    const { rerender } = render(
      <SeverityChip label="Low" active={false} onToggle={() => {}} />,
    );
    const inactive = screen.getByRole("button", { name: "Low" });
    expect(inactive.className).not.toContain("bg-primary text-primary-foreground");
    rerender(<SeverityChip label="Low" active onToggle={() => {}} />);
    expect(screen.getByRole("button", { name: "Low" }).className).toContain(
      "bg-primary text-primary-foreground",
    );
  });

  it("always carries the capitalize class", () => {
    render(<SeverityChip label="Medium" active={false} onToggle={() => {}} />);
    expect(screen.getByRole("button", { name: "Medium" }).className).toContain(
      "capitalize",
    );
  });

  it("is type=button so it never submits an enclosing form", () => {
    render(<SeverityChip label="Info" active={false} onToggle={() => {}} />);
    expect(screen.getByRole("button", { name: "Info" })).toHaveAttribute(
      "type",
      "button",
    );
  });

  it("calls onToggle exactly once per click", () => {
    const onToggle = vi.fn();
    render(<SeverityChip label="Critical" active={false} onToggle={onToggle} />);
    fireEvent.click(screen.getByRole("button", { name: "Critical" }));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });
});
