import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { formatRelative } from "./relativeTime";

const NOW_MS = 1_700_000_000_000;

describe("formatRelative", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(NOW_MS));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it.each([
    [0n, "just now"],
    [3_000_000_000n, "3s ago"],
    [90_000_000_000n, "1m ago"],
    [10n * 60n * 1_000_000_000n, "10m ago"],
    [3n * 60n * 60n * 1_000_000_000n, "3h ago"],
    [25n * 60n * 60n * 1_000_000_000n, "1d ago"],
    [7n * 24n * 60n * 60n * 1_000_000_000n, "7d ago"],
  ])("formats delta %s ns as %s", (deltaNs, expected) => {
    const ts = BigInt(NOW_MS) * 1_000_000n - deltaNs;
    expect(formatRelative(ts)).toBe(expected);
  });

  it("returns 'in the future' for timestamps after now", () => {
    const ts = BigInt(NOW_MS) * 1_000_000n + 60n * 1_000_000_000n;
    expect(formatRelative(ts)).toBe("in the future");
  });

  it("accepts a number millisecond timestamp", () => {
    expect(formatRelative(NOW_MS - 5_000)).toBe("5s ago");
  });
});
