import { describe, it, expect, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";

vi.mock("uplot", () => {
  const setData = vi.fn();
  const destroy = vi.fn();
  const Ctor = vi.fn((_opts: unknown, data: unknown) => ({
    root: document.createElement("div"),
    setData,
    destroy,
    data,
  }));
  Object.assign(Ctor, { __setData: setData, __destroy: destroy });
  return { default: Ctor };
});

import { SeverityStack } from "./SeverityStack";

describe("SeverityStack", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders without error with empty data", () => {
    expect(() =>
      render(<SeverityStack timestamps={[]} info={[]} warn={[]} crit={[]} />),
    ).not.toThrow();
  });

  it("renders with sample data", () => {
    const { container } = render(
      <SeverityStack
        timestamps={[1, 2, 3]}
        info={[10, 20, 30]}
        warn={[5, 8, 3]}
        crit={[1, 0, 2]}
        width={600}
        height={200}
      />,
    );
    expect(container.firstChild).toBeTruthy();
  });

  it("accepts className prop", () => {
    const { container } = render(
      <SeverityStack
        timestamps={[]}
        info={[]}
        warn={[]}
        crit={[]}
        className="sf-severity"
      />,
    );
    expect(container.firstChild).toHaveClass("sf-severity");
  });

  it("accepts annotation marker prop", () => {
    expect(() =>
      render(
        <SeverityStack
          timestamps={[1, 2, 3]}
          info={[10, 20, 30]}
          warn={[5, 8, 3]}
          crit={[0, 0, 1]}
          annotationTs={2}
        />,
      ),
    ).not.toThrow();
  });
});
