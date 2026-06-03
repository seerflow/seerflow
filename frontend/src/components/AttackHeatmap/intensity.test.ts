import { describe, it, expect } from "vitest";
import { intensityLevel, INTENSITY_STYLE, INTENSITY_SWATCHES } from "./intensity";
import type { Intensity } from "./intensity";

describe("intensityLevel", () => {
  it("returns crit when detected && alertCount > 0", () => {
    expect(intensityLevel(true, true, 2, 5)).toBe("crit");
  });

  it("returns warn when detected && alertCount === 0", () => {
    expect(intensityLevel(true, true, 2, 0)).toBe("warn");
  });

  it("returns low when covered && ruleCount > 1 && not detected", () => {
    expect(intensityLevel(true, false, 3, 0)).toBe("low");
  });

  it("returns min when covered && ruleCount === 1 && not detected", () => {
    expect(intensityLevel(true, false, 1, 0)).toBe("min");
  });

  it("returns none when not covered", () => {
    expect(intensityLevel(false, false, 0, 0)).toBe("none");
  });

  it("returns crit even if ruleCount is 0 (detected + alerts wins)", () => {
    expect(intensityLevel(false, true, 0, 1)).toBe("crit");
  });

  it("crit takes priority over low (high ruleCount + detected + alerts)", () => {
    expect(intensityLevel(true, true, 10, 3)).toBe("crit");
  });
});

describe("INTENSITY_STYLE", () => {
  const levels: Intensity[] = ["none", "min", "low", "warn", "crit"];

  it("has an entry for every intensity level", () => {
    for (const level of levels) {
      expect(INTENSITY_STYLE[level]).toBeDefined();
    }
  });

  it("none uses --surface-2 background", () => {
    expect(INTENSITY_STYLE.none.background).toBe("var(--surface-2)");
  });

  it("crit uses --crit background", () => {
    expect(INTENSITY_STYLE.crit.background).toBe("var(--crit)");
  });

  it("warn uses --warn background", () => {
    expect(INTENSITY_STYLE.warn.background).toBe("var(--warn)");
  });

  it("min uses color-mix with 22% accent", () => {
    expect(String(INTENSITY_STYLE.min.background)).toContain("22%");
  });

  it("low uses color-mix with 55% accent", () => {
    expect(String(INTENSITY_STYLE.low.background)).toContain("55%");
  });

  it("all colored levels include a border", () => {
    for (const level of levels) {
      expect(INTENSITY_STYLE[level].border).toBeDefined();
    }
  });
});

describe("INTENSITY_SWATCHES", () => {
  it("has exactly 5 entries", () => {
    expect(INTENSITY_SWATCHES).toHaveLength(5);
  });

  it("levels are in order: none → min → low → warn → crit", () => {
    const levels = INTENSITY_SWATCHES.map((s) => s.level);
    expect(levels).toEqual(["none", "min", "low", "warn", "crit"]);
  });
});
