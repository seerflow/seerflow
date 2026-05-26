import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Sparkline } from "./Sparkline";

describe("Sparkline", () => {
  it("renders without error with empty data", () => {
    expect(() => render(<Sparkline data={[]} />)).not.toThrow();
  });

  it("renders with sample data", () => {
    const data = [
      { t: 1, v: 10 },
      { t: 2, v: 20 },
      { t: 3, v: 15 },
    ];
    const { container } = render(<Sparkline data={data} />);
    expect(container.firstChild).toBeTruthy();
  });

  it("accepts className prop", () => {
    const { container } = render(
      <Sparkline data={[]} className="sf-spark" />,
    );
    expect(container.firstChild).toHaveClass("sf-spark");
  });

  it("accepts optional color prop", () => {
    expect(() =>
      render(
        <Sparkline
          data={[{ t: 1, v: 10 }]}
          color="var(--warn)"
        />,
      ),
    ).not.toThrow();
  });

  it("accepts width and height props", () => {
    expect(() =>
      render(<Sparkline data={[{ t: 1, v: 10 }]} width={80} height={20} />),
    ).not.toThrow();
  });
});
