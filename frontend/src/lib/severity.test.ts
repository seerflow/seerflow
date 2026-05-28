import { describe, it, expect } from "vitest";
import { severityBucket, SEVERITY_CLASS } from "./severity";

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

describe("SEVERITY_CLASS brand-token palette (S-349)", () => {
  it("critical uses the --crit brand token, not a red-* palette literal", () => {
    expect(SEVERITY_CLASS.critical).toContain("text-crit");
    expect(SEVERITY_CLASS.critical).toContain("bg-crit");
    expect(SEVERITY_CLASS.critical).not.toMatch(/red-\d+/);
  });

  it("high uses the --warn brand token, not an orange-* palette literal", () => {
    expect(SEVERITY_CLASS.high).toContain("text-warn");
    expect(SEVERITY_CLASS.high).toContain("bg-warn");
    expect(SEVERITY_CLASS.high).not.toMatch(/orange-\d+/);
  });

  it("medium uses the dedicated --warn-2 brand token (S-350), not bare --warn or a yellow-* literal", () => {
    expect(SEVERITY_CLASS.medium).toContain("text-warn-2");
    expect(SEVERITY_CLASS.medium).toContain("bg-warn-2");
    // distinct from the `high` band: must NOT use the bare `warn` token
    expect(SEVERITY_CLASS.medium).not.toMatch(/\bbg-warn\//);
    expect(SEVERITY_CLASS.medium).not.toMatch(/\btext-warn\b(?!-)/);
    expect(SEVERITY_CLASS.medium).not.toMatch(/yellow-\d+/);
  });

  it("low keeps the neutral slate band (intentional, theme-stable)", () => {
    expect(SEVERITY_CLASS.low).toContain("text-slate-500");
  });
});
