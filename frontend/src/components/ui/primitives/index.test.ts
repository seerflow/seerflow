import { describe, it, expect } from "vitest";

describe("primitives barrel export", () => {
  it("exports all expected primitives without TypeScript errors", async () => {
    const primitives = await import("./index");

    expect(typeof primitives.Panel).toBe("function");
    expect(typeof primitives.MonoLabel).toBe("function");
    expect(typeof primitives.SFBadge).toBe("function");
    expect(typeof primitives.KbdHint).toBe("function");
    expect(typeof primitives.EntityGlyph).toBe("function");
    expect(typeof primitives.Stat).toBe("function");
    expect(typeof primitives.RiskBar).toBe("function");
    expect(typeof primitives.riskLevelFromValue).toBe("function");
    expect(typeof primitives.SideBlock).toBe("function");
    expect(typeof primitives.Legend).toBe("function");
    expect(typeof primitives.LegendItem).toBe("function");
    expect(typeof primitives.FilterChip).toBe("function");
    expect(typeof primitives.FilterRow).toBe("function");
  });

  it("riskLevelFromValue returns correct levels", async () => {
    const { riskLevelFromValue } = await import("./index");
    expect(riskLevelFromValue(0.9)).toBe("crit");
    expect(riskLevelFromValue(0.7)).toBe("warn");
    expect(riskLevelFromValue(0.5)).toBe("accent");
    expect(riskLevelFromValue(0.2)).toBe("mute");
  });
});
