import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Legend, LegendItem } from "./Legend";

describe("LegendItem", () => {
  it("renders the label text", () => {
    const { container } = render(<LegendItem color="var(--accent)" label="Anomalies" />);
    expect(container.textContent).toContain("Anomalies");
  });

  it("has sf-mono class", () => {
    const { container } = render(<LegendItem color="var(--accent)" label="x" />);
    expect(container.querySelector(".sf-mono")).toBeTruthy();
  });

  it("renders a color dot with the given color", () => {
    const { container } = render(<LegendItem color="var(--crit)" label="crit" />);
    const dot = container.querySelector("[style*='crit'], [style*='background']");
    expect(dot).toBeTruthy();
  });
});

describe("Legend", () => {
  it("renders all items", () => {
    const items = [
      { color: "var(--accent)", label: "A" },
      { color: "var(--warn)", label: "B" },
    ];
    const { container } = render(<Legend items={items} />);
    expect(container.textContent).toContain("A");
    expect(container.textContent).toContain("B");
  });
});
