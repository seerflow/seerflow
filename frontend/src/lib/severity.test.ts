import { describe, it, expect } from "vitest";
import { severityBucket } from "./severity";

describe("severityBucket", () => {
  it.each([
    [1, "low"], [8, "low"],
    [9, "medium"], [12, "medium"],
    [13, "high"], [16, "high"],
    [17, "critical"], [24, "critical"],
  ] as const)("id=%i -> %s", (id, bucket) => {
    expect(severityBucket(id)).toBe(bucket);
  });

  it("clamps out-of-range low", () => {
    expect(severityBucket(0)).toBe("low");
  });

  it("clamps out-of-range critical", () => {
    expect(severityBucket(99)).toBe("critical");
  });
});
