import { describe, it, expect } from "vitest";
import { buildStyle } from "./graphStyle";

const tokens = {
  accent: "#a", warn: "#w", crit: "#c", line: "#l", line2: "#l2",
  text: "#text", text2: "#text2", text3: "#text3",
  surface: "#s", surface2: "#s2", bg: "#bg",
} as ReturnType<typeof import("@/lib/theme/resolveTokens").resolveTokens>;

function nodeStyle() {
  const node = buildStyle(tokens).find((r) => r.selector === "node");
  if (!node) throw new Error("node selector missing");
  return node.style as Record<string, unknown>;
}

describe("buildStyle node label legibility", () => {
  it("uses the high-contrast text token (not the muted text-2)", () => {
    const s = nodeStyle();
    expect(s.color).toBe(tokens.text);
    expect(s.color).not.toBe(tokens.text2);
  });

  it("draws a background-colored text outline so labels read over edges", () => {
    const s = nodeStyle();
    expect(s["text-outline-color"]).toBe(tokens.bg);
    expect(Number(s["text-outline-width"])).toBeGreaterThan(0);
  });

  it("keeps the label font compact and uses a concrete (non-CSS-var) family", () => {
    const s = nodeStyle();
    expect(Number(s["font-size"])).toBeLessThanOrEqual(9);
    expect(String(s["font-family"])).not.toContain("var(");
  });
});
