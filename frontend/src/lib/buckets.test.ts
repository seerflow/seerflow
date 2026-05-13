import { describe, expect, it } from "vitest";
import {
  BUCKET_NS,
  RESOLUTION_NS,
  RANGE_NS,
  ALLOWED_RESOLUTIONS,
  bucketStartNs,
  defaultResolution,
  rangeMs,
  resolutionMs,
} from "./buckets";

describe("buckets", () => {
  it("BUCKET_NS is one minute in ns", () => {
    expect(BUCKET_NS).toBe(60n * 1_000_000_000n);
  });

  it.each([
    ["1m", 60n * 1_000_000_000n],
    ["5m", 5n * 60n * 1_000_000_000n],
    ["15m", 15n * 60n * 1_000_000_000n],
    ["1h", 3600n * 1_000_000_000n],
  ] as const)("RESOLUTION_NS[%s] = %s", (r, expected) => {
    expect(RESOLUTION_NS[r]).toBe(expected);
  });

  it.each([
    ["1h", 3600n * 1_000_000_000n],
    ["6h", 6n * 3600n * 1_000_000_000n],
    ["24h", 24n * 3600n * 1_000_000_000n],
    ["7d", 7n * 24n * 3600n * 1_000_000_000n],
  ] as const)("RANGE_NS[%s] = %s", (r, expected) => {
    expect(RANGE_NS[r]).toBe(expected);
  });

  it.each([
    ["1h", ["1m"]],
    ["6h", ["1m", "5m"]],
    ["24h", ["5m", "15m"]],
    ["7d", ["15m", "1h"]],
  ] as const)("ALLOWED_RESOLUTIONS[%s]", (range, expected) => {
    expect(ALLOWED_RESOLUTIONS[range]).toEqual(expected);
  });

  it.each([
    ["1h", "1m"], ["6h", "1m"], ["24h", "5m"], ["7d", "15m"],
  ] as const)("defaultResolution(%s) = %s", (rng, exp) => {
    expect(defaultResolution(rng)).toBe(exp);
  });

  it("bucketStartNs floors to the bucket boundary", () => {
    expect(bucketStartNs(0n, "1m")).toBe(0n);
    expect(bucketStartNs(BUCKET_NS, "1m")).toBe(BUCKET_NS);
    expect(bucketStartNs(BUCKET_NS + 1n, "1m")).toBe(BUCKET_NS);
    expect(bucketStartNs(BUCKET_NS * 3n + 500n, "5m")).toBe(0n);
    expect(bucketStartNs(BUCKET_NS * 6n, "5m")).toBe(BUCKET_NS * 5n);
  });

  it("rangeMs and resolutionMs return number-ms values for chart X scale", () => {
    expect(rangeMs("1h")).toBe(3600 * 1000);
    expect(resolutionMs("5m")).toBe(5 * 60 * 1000);
    expect(rangeMs("7d")).toBe(7 * 24 * 3600 * 1000);
    expect(resolutionMs("1h")).toBe(3600 * 1000);
  });
});
