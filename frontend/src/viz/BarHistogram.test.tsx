import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { BarHistogram } from "./BarHistogram";

describe("BarHistogram", () => {
  it("renders without error with empty data", () => {
    expect(() => render(<BarHistogram data={[]} />)).not.toThrow();
  });

  it("renders with sample data", () => {
    const data = [
      { t: 1, v: 4 },
      { t: 2, v: 12 },
      { t: 3, v: 7 },
    ];
    const { container } = render(<BarHistogram data={data} />);
    expect(container.firstChild).toBeTruthy();
  });

  it("accepts className prop", () => {
    const { container } = render(
      <BarHistogram data={[]} className="sf-histogram" />,
    );
    expect(container.firstChild).toHaveClass("sf-histogram");
  });

  it("accepts threshold prop for spike coloring", () => {
    const data = [
      { t: 1, v: 5 },
      { t: 2, v: 30 },
      { t: 3, v: 8 },
    ];
    expect(() =>
      render(
        <BarHistogram
          data={data}
          threshold={20}
          normalColor="var(--accent)"
          spikeColor="var(--warn)"
        />,
      ),
    ).not.toThrow();
  });

  it("accepts height prop", () => {
    expect(() =>
      render(<BarHistogram data={[{ t: 1, v: 10 }]} height={80} />),
    ).not.toThrow();
  });
});
