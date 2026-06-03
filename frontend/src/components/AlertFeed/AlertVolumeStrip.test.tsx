import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { AlertVolumeStrip } from "./AlertVolumeStrip";

describe("AlertVolumeStrip", () => {
  it("renders an svg strip with stacked bars", () => {
    const { container } = render(<AlertVolumeStrip />);
    const svg = container.querySelector("svg");
    expect(svg).toBeTruthy();
    // Deterministic generator emits a stack of <rect> segments.
    expect(container.querySelectorAll("rect").length).toBeGreaterThan(10);
  });

  it("is deterministic across renders (same rect count)", () => {
    const a = render(<AlertVolumeStrip />).container.querySelectorAll("rect").length;
    const b = render(<AlertVolumeStrip />).container.querySelectorAll("rect").length;
    expect(a).toBe(b);
  });
});
