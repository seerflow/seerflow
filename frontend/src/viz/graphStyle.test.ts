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

describe("buildStyle coerces OKLCH brand tokens to hex (Cytoscape can't parse oklch)", () => {
  const oklchTokens = {
    accent: "oklch(0.745 0.130 283)", warn: "oklch(0.815 0.155 80)",
    crit: "oklch(0.725 0.195 25)", line: "oklch(0.275 0.012 250)",
    line2: "oklch(0.345 0.012 250)", text: "oklch(0.965 0.005 250)",
    text2: "oklch(0.795 0.008 250)", text3: "oklch(0.620 0.010 250)",
    surface: "oklch(0.175 0.012 250)", surface2: "oklch(0.205 0.014 250)",
    bg: "oklch(0.145 0.012 250)",
  } as ReturnType<typeof import("@/lib/theme/resolveTokens").resolveTokens>;

  it("renders label + outline as hex, never raw oklch", () => {
    const node = buildStyle(oklchTokens).find((r) => r.selector === "node");
    const s = node!.style as Record<string, unknown>;
    expect(String(s.color)).toMatch(/^#[0-9a-f]{6}$/i);
    expect(String(s["text-outline-color"])).toMatch(/^#[0-9a-f]{6}$/i);
    expect(String(s.color)).not.toContain("oklch");
  });

  it("renders risk-colored node fill as hex (not the default gray fallback)", () => {
    const node = buildStyle(oklchTokens).find((r) => r.selector === "node");
    const s = node!.style as unknown as Record<string, (ele: { data: (k: string) => number }) => string>;
    const fill = s["background-color"]({ data: () => 0.95 }); // crit-risk node
    expect(fill).toMatch(/^#[0-9a-f]{6}$/i);
  });
});
