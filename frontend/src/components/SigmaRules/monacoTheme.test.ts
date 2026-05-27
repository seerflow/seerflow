/**
 * S-324: monacoTheme utility tests.
 */
import { describe, it, expect } from "vitest";
import { resolveTokens, buildMonacoTheme, SEERFLOW_MONACO_THEME } from "./monacoTheme";

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
