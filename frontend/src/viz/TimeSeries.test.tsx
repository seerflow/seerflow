import { describe, it, expect, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";

// --------------------------------------------------------------------------
// Mock uPlot — we test the wrapper behaviour, not canvas pixel output
// --------------------------------------------------------------------------
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

import uPlot from "uplot";
import { TimeSeries, type TimeSeriesProps } from "./TimeSeries";

type UPlotMock = ReturnType<typeof vi.fn> & {
  __setData: ReturnType<typeof vi.fn>;
  __destroy: ReturnType<typeof vi.fn>;
};

function getUPlotMock() {
  return uPlot as unknown as UPlotMock;
}

// --------------------------------------------------------------------------
const makeData = (): [number[], ...number[][]] => [[1, 2, 3], [10, 20, 30]];

const defaultProps: TimeSeriesProps = {
  data: makeData(),
  width: 400,
  height: 160,
  series: [{ label: "events" }],
};

// --------------------------------------------------------------------------
describe("TimeSeries", () => {
  beforeEach(() => {
    getUPlotMock().mockClear();
    getUPlotMock().__setData.mockClear();
    getUPlotMock().__destroy.mockClear();
  });

  it("renders a container div", () => {
    const { container } = render(<TimeSeries {...defaultProps} />);
    expect(container.firstChild).toBeTruthy();
  });

  it("creates a uPlot instance on mount", () => {
    render(<TimeSeries {...defaultProps} />);
    expect(getUPlotMock()).toHaveBeenCalledTimes(1);
  });

  it("does NOT re-create the instance when data changes", () => {
    const { rerender } = render(<TimeSeries {...defaultProps} />);
    rerender(<TimeSeries {...defaultProps} data={[[4, 5], [40, 50]]} />);
    rerender(<TimeSeries {...defaultProps} data={[[6, 7], [60, 70]]} />);
    expect(getUPlotMock()).toHaveBeenCalledTimes(1);
  });

  it("calls setData imperatively when data prop changes", () => {
    const { rerender } = render(<TimeSeries {...defaultProps} />);
    const newData: [number[], ...number[][]] = [[4, 5], [40, 50]];
    rerender(<TimeSeries {...defaultProps} data={newData} />);
    expect(getUPlotMock().__setData).toHaveBeenCalledWith(newData, false);
  });

  it("passes initial data to the uPlot constructor", () => {
    render(<TimeSeries {...defaultProps} />);
    // Constructor called with opts, data (initial data passed as 2nd arg to uPlot ctor)
    expect(getUPlotMock().mock.calls[0][1]).toEqual(defaultProps.data);
  });

  it("destroys the uPlot instance on unmount", () => {
    const { unmount } = render(<TimeSeries {...defaultProps} />);
    unmount();
    expect(getUPlotMock().__destroy).toHaveBeenCalledTimes(1);
  });

  it("accepts optional className prop", () => {
    const { container } = render(
      <TimeSeries {...defaultProps} className="sf-chart" />,
    );
    expect(container.firstChild).toHaveClass("sf-chart");
  });

  it("creates uPlot with correct width and height", () => {
    render(<TimeSeries {...defaultProps} width={800} height={240} />);
    const opts = getUPlotMock().mock.calls[0][0] as uPlot.Options;
    expect(opts.width).toBe(800);
    expect(opts.height).toBe(240);
  });

  it("includes x-axis + provided series in uPlot opts", () => {
    render(
      <TimeSeries
        {...defaultProps}
        series={[{ label: "info" }, { label: "warn" }]}
      />,
    );
    const opts = getUPlotMock().mock.calls[0][0] as uPlot.Options;
    // series[0] = implicit x-axis; [1],[2] = user series
    expect(opts.series).toHaveLength(3);
  });

  it("does not call setData again if data reference is unchanged", () => {
    const data = makeData();
    const { rerender } = render(<TimeSeries {...defaultProps} data={data} />);
    rerender(<TimeSeries {...defaultProps} data={data} />);
    expect(getUPlotMock().__setData).not.toHaveBeenCalled();
  });
});
