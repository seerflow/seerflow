import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { MonoLabel } from "./MonoLabel";

describe("MonoLabel", () => {
  it("renders the label text", () => {
    const { container } = render(<MonoLabel>events / sec</MonoLabel>);
    expect(container.textContent).toContain("events / sec");
  });

  it("has sf-mono class for mono font", () => {
    const { container } = render(<MonoLabel>label</MonoLabel>);
    const cls = container.firstElementChild?.className ?? "";
    expect(cls).toContain("sf-mono");
  });

  it("has text-text-3 for muted color", () => {
    const { container } = render(<MonoLabel>label</MonoLabel>);
    const cls = container.firstElementChild?.className ?? "";
    expect(cls).toContain("text-text-3");
  });

  it("has uppercase tracking class", () => {
    const { container } = render(<MonoLabel>label</MonoLabel>);
    const cls = container.firstElementChild?.className ?? "";
    expect(cls).toContain("uppercase");
  });

  it("accepts className override", () => {
    const { container } = render(<MonoLabel className="extra">label</MonoLabel>);
    expect(container.firstElementChild?.className).toContain("extra");
  });
});
