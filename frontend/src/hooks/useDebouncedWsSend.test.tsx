import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDebouncedWsSend } from "./useDebouncedWsSend";

describe("useDebouncedWsSend", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it("fires the latest value once after `delay`", async () => {
    const send = vi.fn<(v: number) => void>();
    const { result } = renderHook(() => useDebouncedWsSend(send, 150));

    act(() => { result.current(1); });
    expect(send).not.toHaveBeenCalled();

    await act(async () => { await vi.advanceTimersByTimeAsync(149); });
    expect(send).not.toHaveBeenCalled();

    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith(1);
  });

  it("coalesces rapid calls into a single send with the latest value", async () => {
    const send = vi.fn<(v: string) => void>();
    const { result } = renderHook(() => useDebouncedWsSend(send, 100));

    act(() => {
      result.current("a");
      result.current("b");
      result.current("c");
    });

    await act(async () => { await vi.advanceTimersByTimeAsync(100); });
    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith("c");
  });

  it("cancels a pending timer when the component unmounts", async () => {
    const send = vi.fn<(v: number) => void>();
    const { result, unmount } = renderHook(() => useDebouncedWsSend(send, 100));

    act(() => { result.current(7); });
    unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(200); });
    expect(send).not.toHaveBeenCalled();
  });

  it("uses the latest `send` fn (no stale closure)", async () => {
    const first = vi.fn();
    const second = vi.fn();
    const { result, rerender } = renderHook(
      ({ send }: { send: (v: number) => void }) => useDebouncedWsSend(send, 100),
      { initialProps: { send: first } },
    );

    act(() => { result.current(1); });
    rerender({ send: second });
    await act(async () => { await vi.advanceTimersByTimeAsync(100); });
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledWith(1);
  });

  it("updates debounce window when `delay` changes mid-flight", async () => {
    const send = vi.fn<(v: number) => void>();
    const { result, rerender } = renderHook(
      ({ delay }: { delay: number }) => useDebouncedWsSend(send, delay),
      { initialProps: { delay: 500 } },
    );

    act(() => { result.current(1); });
    rerender({ delay: 50 });
    act(() => { result.current(2); });
    await act(async () => { await vi.advanceTimersByTimeAsync(50); });
    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith(2);
  });
});
