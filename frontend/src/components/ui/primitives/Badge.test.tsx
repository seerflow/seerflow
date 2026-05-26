import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { SFBadge } from "./Badge";

describe("SFBadge", () => {
  it("renders children", () => {
    const { container } = render(<SFBadge>crit</SFBadge>);
    expect(container.textContent).toContain("crit");
  });

  it("accent variant has accent color reference", () => {
    const { container } = render(<SFBadge variant="accent">label</SFBadge>);
    const cls = container.firstElementChild?.className ?? "";
    expect(cls).toMatch(/accent/);
  });

  it("warn variant has warn color reference", () => {
    const { container } = render(<SFBadge variant="warn">label</SFBadge>);
    const cls = container.firstElementChild?.className ?? "";
    expect(cls).toMatch(/warn/);
  });

  it("crit variant has crit color reference", () => {
    const { container } = render(<SFBadge variant="crit">label</SFBadge>);
    const cls = container.firstElementChild?.className ?? "";
    expect(cls).toMatch(/crit/);
  });

  it("info variant has info color reference", () => {
    const { container } = render(<SFBadge variant="info">label</SFBadge>);
    const cls = container.firstElementChild?.className ?? "";
    expect(cls).toMatch(/info/);
  });

  it("mute variant has muted color reference", () => {
    const { container } = render(<SFBadge variant="mute">label</SFBadge>);
    const cls = container.firstElementChild?.className ?? "";
    expect(cls).toMatch(/text-3|mute/);
  });

  it("has sf-mono class (mono label style)", () => {
    const { container } = render(<SFBadge>x</SFBadge>);
    expect(container.firstElementChild?.className).toContain("sf-mono");
  });
});
