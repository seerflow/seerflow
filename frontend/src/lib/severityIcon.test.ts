import { describe, expect, it } from "vitest";
import { severityIcon } from "./severityIcon";

describe("severityIcon", () => {
  it.each([
    [0, "TRACE", "neutral"],
    [1, "DEBUG", "neutral"],
    [2, "INFO", "info"],
    [3, "NOTICE", "info"],
    [4, "WARN", "warn"],
    [5, "ERROR", "error"],
    [6, "FATAL", "crit"],
  ])("severity_id %i → label %s, tone %s", (id, label, tone) => {
    const r = severityIcon(id);
    expect(r.label).toBe(label);
    expect(r.tone).toBe(tone);
    expect(typeof r.emoji).toBe("string");
    expect(r.emoji.length).toBeGreaterThan(0);
  });

  it("clamps out-of-range ids to nearest endpoint", () => {
    expect(severityIcon(-1).label).toBe("TRACE");
    expect(severityIcon(99).label).toBe("FATAL");
  });
});
