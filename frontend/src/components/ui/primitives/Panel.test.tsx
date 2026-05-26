import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Panel } from "./Panel";

describe("Panel", () => {
  it("renders a div", () => {
    const { container } = render(<Panel>content</Panel>);
    expect(container.querySelector("div")).toBeTruthy();
  });

  it("has bg-surface class", () => {
    const { container } = render(<Panel>x</Panel>);
    expect(container.firstElementChild?.className).toContain("bg-surface");
  });

  it("has border and border-line classes", () => {
    const { container } = render(<Panel>x</Panel>);
    const cls = container.firstElementChild?.className ?? "";
    expect(cls).toContain("border");
    expect(cls).toContain("border-line");
  });

  it("renders children", () => {
    const { container } = render(<Panel><span id="child">hi</span></Panel>);
    expect(container.querySelector("#child")).toBeTruthy();
  });

  it("accepts additional className", () => {
    const { container } = render(<Panel className="custom-class">x</Panel>);
    expect(container.firstElementChild?.className).toContain("custom-class");
  });
});
