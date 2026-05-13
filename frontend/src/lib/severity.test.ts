import { describe, it, expect } from "vitest";
import { severityBucket } from "./severity";

describe("severityBucket (OCSF 0..6)", () => {
  it.each([
    [0, "low"],  [1, "low"],  [2, "low"],
    [3, "medium"],
    [4, "high"],
    [5, "critical"], [6, "critical"],
  ] as const)("id=%i -> %s", (id, bucket) => {
    expect(severityBucket(id)).toBe(bucket);
  });

  it("treats negative ids as low (defensive)", () => {
    expect(severityBucket(-1)).toBe("low");
  });

  it("treats out-of-range high ids as critical (defensive)", () => {
    expect(severityBucket(99)).toBe("critical");
  });
});
