import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  isDemoMode,
  startDemoBridge,
  stopDemoBridge,
} from "./index";

// --------------------------------------------------------------------------
// isDemoMode
// --------------------------------------------------------------------------
describe("isDemoMode", () => {
  afterEach(() => {
    // Reset search params
    Object.defineProperty(window, "location", {
      value: { ...window.location, search: "" },
      writable: true,
      configurable: true,
    });
  });

  it("returns false when no ?demo param", () => {
    Object.defineProperty(window, "location", {
      value: { ...window.location, search: "" },
      writable: true,
      configurable: true,
    });
    expect(isDemoMode()).toBe(false);
  });

  it("returns true when ?demo=1 is present", () => {
    Object.defineProperty(window, "location", {
      value: { ...window.location, search: "?demo=1" },
      writable: true,
      configurable: true,
    });
    expect(isDemoMode()).toBe(true);
  });

  it("returns true when ?demo=true is present", () => {
    Object.defineProperty(window, "location", {
      value: { ...window.location, search: "?demo=true" },
      writable: true,
      configurable: true,
    });
    expect(isDemoMode()).toBe(true);
  });

  it("returns false when ?demo=0", () => {
    Object.defineProperty(window, "location", {
      value: { ...window.location, search: "?demo=0" },
      writable: true,
      configurable: true,
    });
    expect(isDemoMode()).toBe(false);
  });
});

// --------------------------------------------------------------------------
// startDemoBridge / stopDemoBridge
// --------------------------------------------------------------------------
describe("startDemoBridge", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    stopDemoBridge();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("starts without throwing", () => {
    expect(() => startDemoBridge({ intervalMs: 1000 })).not.toThrow();
  });

  it("can be started and stopped multiple times without error", () => {
    startDemoBridge({ intervalMs: 1000 });
    stopDemoBridge();
    startDemoBridge({ intervalMs: 1000 });
    stopDemoBridge();
  });

  it("does not re-start if already running", () => {
    const setIntervalSpy = vi.spyOn(window, "setInterval");
    startDemoBridge({ intervalMs: 1000 });
    startDemoBridge({ intervalMs: 1000 });
    // Should only call setInterval once
    expect(setIntervalSpy).toHaveBeenCalledTimes(1);
    stopDemoBridge();
  });

  it("calls onTick callback on each interval", () => {
    const onTick = vi.fn();
    startDemoBridge({ intervalMs: 500, onTick });
    vi.advanceTimersByTime(1500);
    expect(onTick).toHaveBeenCalled();
    stopDemoBridge();
  });

  it("stopDemoBridge clears the timer so onTick stops", () => {
    const onTick = vi.fn();
    startDemoBridge({ intervalMs: 500, onTick });
    stopDemoBridge();
    vi.advanceTimersByTime(2000);
    expect(onTick).not.toHaveBeenCalled();
  });
});
