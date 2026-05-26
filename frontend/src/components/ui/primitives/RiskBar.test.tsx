import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { RiskBar } from "./RiskBar";

describe("RiskBar", () => {
  it("renders a track element", () => {
    const { container } = render(<RiskBar value={0.5} />);
    expect(container.firstElementChild).toBeTruthy();
  });

  it("crit level uses crit color class or style", () => {
    const { container } = render(<RiskBar value={0.85} level="crit" />);
    const fill = container.querySelector("[class*='crit'], [style*='crit']");
    expect(fill).toBeTruthy();
  });

  it("warn level uses warn color", () => {
    const { container } = render(<RiskBar value={0.7} level="warn" />);
    const fill = container.querySelector("[class*='warn'], [style*='warn']");
    expect(fill).toBeTruthy();
  });

  it("accent level uses accent color", () => {
    const { container } = render(<RiskBar value={0.5} level="accent" />);
    const fill = container.querySelector("[class*='accent'], [style*='accent']");
    expect(fill).toBeTruthy();
  });

  it("renders a 3px-high track by default", () => {
    const { container } = render(<RiskBar value={0.5} />);
    const track = container.firstElementChild as HTMLElement;
    expect(track?.style.height === "3px" || track?.className.includes("h-[3px]")).toBe(true);
  });
});
