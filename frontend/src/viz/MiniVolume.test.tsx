import { describe, it, expect, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";

vi.mock("uplot", () => {
  const setData = vi.fn();
  const destroy = vi.fn();
  const Ctor = vi.fn(() => ({
    root: document.createElement("div"),
    setData,
    destroy,
  }));
  Object.assign(Ctor, { __setData: setData, __destroy: destroy });
  return { default: Ctor };
});

import { MiniVolume } from "./MiniVolume";

describe("MiniVolume", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders without error with empty data", () => {
    expect(() =>
      render(<MiniVolume timestamps={[]} values={[]} />),
    ).not.toThrow();
  });

  it("renders with sample data", () => {
    const ts = Array.from({ length: 60 }, (_, i) => i);
    const vals = Array.from({ length: 60 }, (_, i) => i * 2);
    const { container } = render(
      <MiniVolume timestamps={ts} values={vals} width={600} height={32} />,
    );
    expect(container.firstChild).toBeTruthy();
  });

  it("accepts className prop", () => {
    const { container } = render(
      <MiniVolume timestamps={[]} values={[]} className="sf-mini-vol" />,
    );
    expect(container.firstChild).toHaveClass("sf-mini-vol");
  });

  it("accepts optional normalColor prop", () => {
    expect(() =>
      render(
        <MiniVolume
          timestamps={[1, 2, 3]}
          values={[10, 200, 5]}
          normalColor="var(--accent)"
        />,
      ),
    ).not.toThrow();
  });
});
