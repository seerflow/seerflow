/**
 * S-324: monacoTheme utility tests.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  resolveTokens,
  buildMonacoTheme,
  SEERFLOW_MONACO_THEME,
  oklchToHex,
} from "./monacoTheme";

const HEX_RE = /^#?(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/;
const HEX_WITH_ALPHA_RE = /^#?(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/;

describe("resolveTokens", () => {
  it("returns an object with all expected keys", () => {
    const tokens = resolveTokens();
    const expectedKeys = [
      "bg", "surface", "surface2", "text", "text2", "text3",
      "accent", "accent2", "line", "crit", "warn",
    ];
    for (const key of expectedKeys) {
      expect(tokens).toHaveProperty(key);
    }
  });

  it("returns string values for all tokens", () => {
    const tokens = resolveTokens();
    for (const [, val] of Object.entries(tokens)) {
      expect(typeof val).toBe("string");
    }
  });

  it("returns non-empty fallbacks when CSS vars are unavailable", () => {
    const tokens = resolveTokens();
    for (const [, val] of Object.entries(tokens)) {
      expect(val.length).toBeGreaterThan(0);
    }
  });
});

describe("buildMonacoTheme", () => {
  it("uses vs-dark as base", () => {
    const theme = buildMonacoTheme();
    expect(theme.base).toBe("vs-dark");
  });

  it("sets editor.background color", () => {
    const theme = buildMonacoTheme();
    expect(theme.colors).toHaveProperty("editor.background");
    expect(theme.colors["editor.background"].length).toBeGreaterThan(0);
  });

  it("includes key.yaml rule", () => {
    const theme = buildMonacoTheme();
    const keyYaml = theme.rules.find((r) => r.token === "key.yaml");
    expect(keyYaml).toBeDefined();
    expect(keyYaml?.foreground).toBeDefined();
  });

  it("includes string.yaml rule", () => {
    const theme = buildMonacoTheme();
    const stringYaml = theme.rules.find((r) => r.token === "string.yaml");
    expect(stringYaml).toBeDefined();
    expect(stringYaml?.foreground).toBeDefined();
  });

  it("includes comment rule with italic style", () => {
    const theme = buildMonacoTheme();
    const comment = theme.rules.find((r) => r.token === "comment");
    expect(comment).toBeDefined();
    expect(comment?.fontStyle).toBe("italic");
  });
});

describe("SEERFLOW_MONACO_THEME", () => {
  it("is a non-empty string", () => {
    expect(typeof SEERFLOW_MONACO_THEME).toBe("string");
    expect(SEERFLOW_MONACO_THEME.length).toBeGreaterThan(0);
  });
});

/**
 * S-343 regression — Monaco's theme parser only accepts hex colors. The brand
 * tokens are OKLCH, so the live computed CSS-var values are NOT Monaco-safe;
 * feeding `oklch(...)` to `defineTheme`/`setTheme` throws "Illegal value for
 * token color" and unmounts the React tree (blank screen). `resolveTokens` must
 * fall back to the hex constants whenever the CSS var is not a hex literal.
 */
describe("resolveTokens — Monaco-hex safety (S-343)", () => {
  const origGCS = window.getComputedStyle;
  afterEach(() => {
    window.getComputedStyle = origGCS;
  });

  it("falls back to hex constants when CSS vars return OKLCH (brand default)", () => {
    window.getComputedStyle = vi.fn(
      () =>
        ({
          getPropertyValue: () => "oklch(.965 .005 250)",
        }) as unknown as CSSStyleDeclaration,
    );
    const tokens = resolveTokens();
    for (const [, val] of Object.entries(tokens)) {
      expect(val).toMatch(HEX_RE);
    }
  });

  it("falls back to hex constants when CSS vars return rgb(...)", () => {
    window.getComputedStyle = vi.fn(
      () =>
        ({
          getPropertyValue: () => "rgb(125, 158, 248)",
        }) as unknown as CSSStyleDeclaration,
    );
    const tokens = resolveTokens();
    for (const [, val] of Object.entries(tokens)) {
      expect(val).toMatch(HEX_RE);
    }
  });

  it("accepts a hex CSS-var value (passes through unchanged)", () => {
    window.getComputedStyle = vi.fn(
      () =>
        ({
          getPropertyValue: (n: string) => (n === "--accent" ? "#abcdef" : ""),
        }) as unknown as CSSStyleDeclaration,
    );
    const tokens = resolveTokens();
    expect(tokens.accent).toBe("#abcdef");
  });
});

/**
 * S-344 — OKLCH→hex converter for Monaco. Brand tokens are OKLCH; the S-343
 * hard-coded `FALLBACKS` hex didn't match the brand palette (e.g. `--accent`
 * is violet `oklch(0.745 0.130 283)` but the fallback was indigo `#7c9ef8`).
 * Converting the live OKLCH at runtime keeps Monaco visually consistent.
 */
describe("oklchToHex (S-344)", () => {
  it("maps oklch(1 0 0) to #ffffff (white extreme)", () => {
    expect(oklchToHex("oklch(1 0 0)")).toBe("#ffffff");
  });

  it("maps oklch(0 0 0) to #000000 (black extreme)", () => {
    expect(oklchToHex("oklch(0 0 0)")).toBe("#000000");
  });

  it("accepts percent-L notation", () => {
    expect(oklchToHex("oklch(100% 0 0)")).toBe("#ffffff");
  });

  it("returns null on unparseable input", () => {
    expect(oklchToHex("rgb(1, 2, 3)")).toBeNull();
    expect(oklchToHex("not a color")).toBeNull();
    expect(oklchToHex("")).toBeNull();
  });

  it("maps the brand `--accent` oklch(0.745 0.130 283) into the violet (h≈283) sRGB region (not indigo)", () => {
    const hex = oklchToHex("oklch(0.745 0.130 283)");
    expect(hex).not.toBeNull();
    expect(hex).toMatch(/^#[0-9a-f]{6}$/);
    // R < B (it's bluish-violet, not red/yellow); B should be the strongest channel.
    const r = parseInt(hex!.slice(1, 3), 16);
    const g = parseInt(hex!.slice(3, 5), 16);
    const b = parseInt(hex!.slice(5, 7), 16);
    expect(b).toBeGreaterThan(r);
    expect(b).toBeGreaterThan(g);
    // And NOT the old indigo fallback "#7c9ef8" — visibly different.
    expect(hex).not.toBe("#7c9ef8");
  });
});

describe("resolveTokens — OKLCH from CSS is converted to brand hex (S-344)", () => {
  const origGCS = window.getComputedStyle;
  afterEach(() => {
    window.getComputedStyle = origGCS;
  });

  it("converts the OKLCH brand accent to its real hex (not the FALLBACKS indigo)", () => {
    window.getComputedStyle = vi.fn(
      () =>
        ({
          getPropertyValue: (n: string) =>
            n === "--accent" ? "oklch(0.745 0.130 283)" : "",
        }) as unknown as CSSStyleDeclaration,
    );
    const tokens = resolveTokens();
    // Hex shape + violet character (b > r, b > g) — the visible-correctness check.
    expect(tokens.accent).toMatch(/^#[0-9a-f]{6}$/);
    expect(tokens.accent).not.toBe("#7c9ef8");
    const r = parseInt(tokens.accent.slice(1, 3), 16);
    const g = parseInt(tokens.accent.slice(3, 5), 16);
    const b = parseInt(tokens.accent.slice(5, 7), 16);
    expect(b).toBeGreaterThan(r);
    expect(b).toBeGreaterThan(g);
  });
});

describe("buildMonacoTheme — produced colors are all Monaco-safe hex (S-343)", () => {
  const origGCS = window.getComputedStyle;
  beforeEach(() => {
    // Worst-case env: every CSS var is OKLCH (live browser w/ brand tokens).
    window.getComputedStyle = vi.fn(
      () =>
        ({
          getPropertyValue: () => "oklch(.965 .005 250)",
        }) as unknown as CSSStyleDeclaration,
    );
  });
  afterEach(() => {
    window.getComputedStyle = origGCS;
  });

  it("every rule.foreground is a hex literal Monaco accepts", () => {
    const theme = buildMonacoTheme();
    for (const r of theme.rules) {
      if (r.foreground !== undefined) {
        expect(r.foreground).toMatch(HEX_WITH_ALPHA_RE);
      }
    }
  });

  it("every theme color is a hex literal (with optional alpha suffix)", () => {
    const theme = buildMonacoTheme();
    for (const [, v] of Object.entries(theme.colors)) {
      expect(v).toMatch(HEX_WITH_ALPHA_RE);
    }
  });
});
