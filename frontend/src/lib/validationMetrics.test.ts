import { describe, it, expect, beforeEach, vi } from "vitest";
import * as metrics from "./validationMetrics";
import { logger } from "./logger";

vi.mock("./logger", () => ({ logger: { warn: vi.fn(), info: vi.fn(), error: vi.fn() } }));

describe("validationMetrics", () => {
  beforeEach(() => {
    metrics._resetForTests();
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-04-22T00:00:00Z"));
    (logger.warn as ReturnType<typeof vi.fn>).mockClear();
  });

  it("incrementDropped tracks per-kind counts", () => {
    metrics.incrementDropped("ws:alert");
    metrics.incrementDropped("ws:alert");
    metrics.incrementDropped("rest:event");
    expect(metrics.getCounters()).toEqual({ "ws:alert": 2, "rest:event": 1 });
  });

  it("warnThrottled fires once per 60s window per kind", () => {
    metrics.warnThrottled("ws:alert", [{ kind: "validation" }]);
    metrics.warnThrottled("ws:alert", [{ kind: "validation" }]);
    expect(logger.warn).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(60_000);
    metrics.warnThrottled("ws:alert", [{ kind: "validation" }]);
    expect(logger.warn).toHaveBeenCalledTimes(2);
  });

  it("warnThrottled isolates kinds", () => {
    metrics.warnThrottled("ws:alert", []);
    metrics.warnThrottled("rest:event", []);
    expect(logger.warn).toHaveBeenCalledTimes(2);
  });

  it("_resetForTests clears counters and throttle state", () => {
    metrics.incrementDropped("x");
    metrics.warnThrottled("x", []);
    metrics._resetForTests();
    expect(metrics.getCounters()).toEqual({});
    metrics.warnThrottled("x", []);
    expect(logger.warn).toHaveBeenCalledTimes(2);
  });
});
