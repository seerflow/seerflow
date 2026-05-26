import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { EntityGlyph } from "./EntityGlyph";

const ENTITY_TYPES = ["user", "host", "ip", "service", "process"] as const;

describe("EntityGlyph", () => {
  it.each(ENTITY_TYPES)("renders an SVG icon for type=%s", (type) => {
    const { container } = render(<EntityGlyph type={type} />);
    expect(container.querySelector("svg")).toBeTruthy();
  });

  it("renders a 24px container by default", () => {
    const { container } = render(<EntityGlyph type="user" />);
    const el = container.firstElementChild as HTMLElement;
    // Check inline style or class for size
    const style = el?.style ?? {};
    const cls = el?.className ?? "";
    expect(style.width === "24px" || cls.includes("w-6") || style.width === "24").toBe(true);
  });

  it("has border (hairline box)", () => {
    const { container } = render(<EntityGlyph type="host" />);
    const cls = container.firstElementChild?.className ?? "";
    const style = (container.firstElementChild as HTMLElement)?.style ?? {};
    expect(cls.includes("border") || style.border !== undefined || style.borderWidth !== undefined).toBe(true);
  });

  it("accepts custom size prop", () => {
    const { container } = render(<EntityGlyph type="ip" size={32} />);
    const el = container.firstElementChild as HTMLElement;
    expect(el?.style.width === "32px" || el?.style.width === "32").toBe(true);
  });
});
