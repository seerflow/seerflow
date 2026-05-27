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

import { MiniVolume, computeBarColors, selectBarColor, makeBarPaths } from "./MiniVolume";

const COLORS = { normalColor: "n", warnColor: "w", critColor: "c" };

describe("makeBarPaths", () => {
  function fakeU(values: number[]) {
    const fills: string[] = [];
    const rects: number[][] = [];
    const ctx = {
      save: () => undefined,
      restore: () => undefined,
      fillRect: (...a: number[]) => rects.push(a),
      set fillStyle(v: string) {
        fills.push(v);
      },
    };
    const u = {
      ctx,
      bbox: { width: 400 },
      data: [values.map((_, i) => i), values],
      valToPos: (v: number) => v,
    };
    return { u, fills, rects };
  }

  it("fills each drawn bar with its computed color and skips null values", () => {
    const values = [1, null as unknown as number, 100];
    const { u, fills, rects } = fakeU(values);
    const paths = makeBarPaths([1, 0, 100], { ...COLORS });
    // crit threshold = max (100) → bar[2] is crit; bar[0] normal; bar[1] null → skipped.
    const ret = paths!(u as never, 1, 0, 2);
    expect(ret).toBeNull();
    expect(rects).toHaveLength(2); // the null bar produced no rect
    expect(fills).toContain("c");
    expect(fills).toContain("n");
  });

  it("falls back to normalColor when no color is resolved for an index", () => {
    const { u, fills } = fakeU([5]);
    // values passed for color computation is empty → computeBarColors returns [],
    // so colors[i] is undefined and the draw falls back to normalColor.
    const paths = makeBarPaths([], { ...COLORS });
    paths!(u as never, 1, 0, 0);
    expect(fills).toEqual(["n"]);
  });
});

describe("selectBarColor", () => {
  it("returns crit color at/above the crit threshold", () => {
    expect(
      selectBarColor(100, { critThreshold: 80, warnThreshold: 50, ...COLORS }),
    ).toBe("c");
  });

  it("returns warn color at/above warn but below crit", () => {
    expect(
      selectBarColor(60, { critThreshold: 80, warnThreshold: 50, ...COLORS }),
    ).toBe("w");
  });

  it("returns normal color below the warn threshold", () => {
    expect(
      selectBarColor(10, { critThreshold: 80, warnThreshold: 50, ...COLORS }),
    ).toBe("n");
  });

  it("treats a value exactly at the warn threshold as warn", () => {
    expect(
      selectBarColor(50, { critThreshold: 80, warnThreshold: 50, ...COLORS }),
    ).toBe("w");
  });
});

describe("computeBarColors", () => {
  it("derives thresholds from data when none are passed (spikes get crit)", () => {
    const colors = computeBarColors([1, 1, 1, 100], COLORS);
    expect(colors).toHaveLength(4);
    expect(colors[3]).toBe("c");
    expect(colors[0]).toBe("n");
  });

  it("returns all-normal for empty data", () => {
    expect(computeBarColors([], COLORS)).toEqual([]);
  });

  it("returns all-normal for a flat series (no spikes)", () => {
    const colors = computeBarColors([5, 5, 5, 5], COLORS);
    expect(colors.every((c) => c === "n")).toBe(true);
  });

  it("honors explicit thresholds over derived ones", () => {
    const colors = computeBarColors([10, 20, 30], {
      ...COLORS,
      critThreshold: 25,
      warnThreshold: 15,
    });
    expect(colors).toEqual(["n", "w", "c"]);
  });
});

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

  it("passes a custom bar-draw paths fn to the uPlot series", async () => {
    const uPlot = (await import("uplot")).default as unknown as { mock: { calls: unknown[][] } };
    render(
      <MiniVolume timestamps={[1, 2, 3, 4]} values={[1, 1, 1, 100]} />,
    );
    const opts = uPlot.mock.calls[0][0] as {
      series: Array<{ paths?: unknown }>;
    };
    // series[0] is the implicit x-axis; series[1] is our volume series.
    expect(typeof opts.series[1].paths).toBe("function");
  });

  it("renders spike data without throwing (uPlot mocked)", () => {
    expect(() =>
      render(
        <MiniVolume
          timestamps={[1, 2, 3, 4]}
          values={[2, 3, 2, 250]}
          critColor="var(--crit)"
          warnColor="var(--warn)"
        />,
      ),
    ).not.toThrow();
  });
});
