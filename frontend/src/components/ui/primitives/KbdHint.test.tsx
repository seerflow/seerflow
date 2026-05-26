import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { KbdHint } from "./KbdHint";

describe("KbdHint", () => {
  it("renders a kbd element", () => {
    const { container } = render(<KbdHint>⌘K</KbdHint>);
    expect(container.querySelector("kbd")).toBeTruthy();
  });

  it("renders key text", () => {
    const { container } = render(<KbdHint>⌘K</KbdHint>);
    expect(container.textContent).toBe("⌘K");
  });

  it("has sf-mono class", () => {
    const { container } = render(<KbdHint>K</KbdHint>);
    expect(container.querySelector("kbd")?.className).toContain("sf-mono");
  });

  it("has border class for hairline box", () => {
    const { container } = render(<KbdHint>K</KbdHint>);
    expect(container.querySelector("kbd")?.className).toContain("border");
  });
});
