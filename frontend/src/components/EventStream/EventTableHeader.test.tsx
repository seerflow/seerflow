import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { EventTableHeader } from "./EventTableHeader";

describe("EventTableHeader", () => {
  it("renders all six column labels", () => {
    render(<EventTableHeader />);
    for (const col of ["timestamp", "level", "source", "host", "logger", "message"]) {
      expect(screen.getByText(col, { exact: true })).toBeInTheDocument();
    }
  });

  it("uses CSS grid layout matching EventRow", () => {
    const { container } = render(<EventTableHeader />);
    const header = container.firstChild as HTMLElement;
    expect(header.style.display).toBe("grid");
    expect(header.style.gridTemplateColumns).toContain("110px");
  });

  it("applies sf-mono class for monospace styling", () => {
    const { container } = render(<EventTableHeader />);
    const header = container.firstChild as HTMLElement;
    expect(header.className).toMatch(/sf-mono/);
  });
});
