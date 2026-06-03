import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { SideBlock } from "./SideBlock";

describe("SideBlock", () => {
  it("renders the title", () => {
    const { container } = render(<SideBlock title="Entities">body</SideBlock>);
    expect(container.textContent).toContain("Entities");
  });

  it("renders children", () => {
    const { container } = render(
      <SideBlock title="Entities"><span id="body">content</span></SideBlock>
    );
    expect(container.querySelector("#body")).toBeTruthy();
  });

  it("title has sf-mono class", () => {
    const { container } = render(<SideBlock title="Entities">x</SideBlock>);
    const titleEl = container.querySelector(".sf-mono");
    expect(titleEl).toBeTruthy();
  });

  it("has a hairline bottom border on the title section", () => {
    const { container } = render(<SideBlock title="T">x</SideBlock>);
    const titleSection = container.querySelector("[class*='border-b']");
    expect(titleSection).toBeTruthy();
  });
});
