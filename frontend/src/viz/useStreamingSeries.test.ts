import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import {
  createRingBuffer,
  useStreamingSeries,
} from "./useStreamingSeries";

// --------------------------------------------------------------------------
// RingBuffer pure unit tests
// --------------------------------------------------------------------------
describe("createRingBuffer", () => {
  it("starts empty with zero length", () => {
    const buf = createRingBuffer(5);
    expect(buf.length).toBe(0);
    expect(buf.capacity).toBe(5);
  });

  it("push fills up to capacity", () => {
    const buf = createRingBuffer(3);
    buf.push(1, 10);
    buf.push(2, 20);
    buf.push(3, 30);
    expect(buf.length).toBe(3);
    expect(buf.toArrays()).toEqual({
      timestamps: [1, 2, 3],
      values: [[10, 20, 30]],
    });
  });

  it("oldest sample is overwritten when capacity exceeded", () => {
    const buf = createRingBuffer(3);
    buf.push(1, 10);
    buf.push(2, 20);
    buf.push(3, 30);
    buf.push(4, 40); // should overwrite timestamp=1
    expect(buf.length).toBe(3);
    const { timestamps, values } = buf.toArrays();
    expect(timestamps).toEqual([2, 3, 4]);
    expect(values[0]).toEqual([20, 30, 40]);
  });

  it("wraps around multiple times correctly", () => {
    const buf = createRingBuffer(3);
    for (let i = 1; i <= 9; i++) buf.push(i, i * 100);
    const { timestamps, values } = buf.toArrays();
    expect(timestamps).toEqual([7, 8, 9]);
    expect(values[0]).toEqual([700, 800, 900]);
  });

  it("supports multi-series push (matching valueSeries.length)", () => {
    const buf = createRingBuffer<[number, number]>(4);
    buf.push(1, [10, 1]);
    buf.push(2, [20, 2]);
    buf.push(3, [30, 3]);
    const { timestamps, values } = buf.toArrays();
    expect(timestamps).toEqual([1, 2, 3]);
    expect(values[0]).toEqual([10, 20, 30]);
    expect(values[1]).toEqual([1, 2, 3]);
  });

  it("multi-series wrap-around correct", () => {
    const buf = createRingBuffer<[number, number]>(3);
    buf.push(1, [10, 1]);
    buf.push(2, [20, 2]);
    buf.push(3, [30, 3]);
    buf.push(4, [40, 4]);
    const { timestamps, values } = buf.toArrays();
    expect(timestamps).toEqual([2, 3, 4]);
    expect(values[0]).toEqual([20, 30, 40]);
    expect(values[1]).toEqual([2, 3, 4]);
  });

  it("clear() resets to empty", () => {
    const buf = createRingBuffer(5);
    buf.push(1, 10);
    buf.push(2, 20);
    buf.clear();
    expect(buf.length).toBe(0);
    const { timestamps, values } = buf.toArrays();
    expect(timestamps).toEqual([]);
    expect(values[0]).toEqual([]);
  });

  it("toArrays() returns new array references each call (immutable snapshot)", () => {
    const buf = createRingBuffer(3);
    buf.push(1, 10);
    const a1 = buf.toArrays();
    const a2 = buf.toArrays();
    expect(a1.timestamps).not.toBe(a2.timestamps);
    expect(a1.values[0]).not.toBe(a2.values[0]);
  });

  it("capacity 1 always keeps only latest", () => {
    const buf = createRingBuffer(1);
    buf.push(1, 100);
    buf.push(2, 200);
    buf.push(3, 300);
    const { timestamps, values } = buf.toArrays();
    expect(timestamps).toEqual([3]);
    expect(values[0]).toEqual([300]);
  });
});

// --------------------------------------------------------------------------
// useStreamingSeries hook tests
// --------------------------------------------------------------------------
describe("useStreamingSeries", () => {
  it("returns initial empty arrays with default capacity 900", () => {
    const { result } = renderHook(() => useStreamingSeries());
    expect(result.current.data.timestamps).toEqual([]);
    expect(result.current.data.values).toEqual([[]]);
    expect(result.current.capacity).toBe(900);
  });

  it("accepts custom capacity", () => {
    const { result } = renderHook(() => useStreamingSeries({ capacity: 60 }));
    expect(result.current.capacity).toBe(60);
  });

  it("push updates data and re-renders", () => {
    const { result } = renderHook(() => useStreamingSeries({ capacity: 5 }));
    act(() => result.current.push(1000, 42));
    expect(result.current.data.timestamps).toEqual([1000]);
    expect(result.current.data.values[0]).toEqual([42]);
  });

  it("oldest overwritten when capacity exceeded via hook", () => {
    const { result } = renderHook(() => useStreamingSeries({ capacity: 2 }));
    act(() => {
      result.current.push(1, 10);
      result.current.push(2, 20);
      result.current.push(3, 30);
    });
    expect(result.current.data.timestamps).toEqual([2, 3]);
    expect(result.current.data.values[0]).toEqual([20, 30]);
  });

  it("clear() empties the buffer", () => {
    const { result } = renderHook(() => useStreamingSeries({ capacity: 5 }));
    act(() => {
      result.current.push(1, 10);
      result.current.push(2, 20);
    });
    act(() => result.current.clear());
    expect(result.current.data.timestamps).toEqual([]);
    expect(result.current.data.values[0]).toEqual([]);
  });

  it("data reference changes on push (no stale captures)", () => {
    const { result } = renderHook(() => useStreamingSeries({ capacity: 3 }));
    const before = result.current.data;
    act(() => result.current.push(1, 10));
    expect(result.current.data).not.toBe(before);
  });

  it("multi-series: push tuple and get parallel value arrays", () => {
    const { result } = renderHook(() =>
      useStreamingSeries<[number, number]>({ capacity: 3 }),
    );
    act(() => {
      result.current.push(1, [10, 1]);
      result.current.push(2, [20, 2]);
    });
    expect(result.current.data.values[0]).toEqual([10, 20]);
    expect(result.current.data.values[1]).toEqual([1, 2]);
  });
});
