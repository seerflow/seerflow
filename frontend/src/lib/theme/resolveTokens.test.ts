import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  resolveTokens,
  subscribeToThemeChanges,
  THEME_EVENT,
  type ThemeTokens,
} from "./resolveTokens";

// --------------------------------------------------------------------------
// Helper: build a mock element with a fake getComputedStyle
// --------------------------------------------------------------------------
function makeEl(vars: Record<string, string>): HTMLElement {
  const el = document.createElement("div");
  vi.spyOn(window, "getComputedStyle").mockReturnValue({
    getPropertyValue: (prop: string) => vars[prop.trim()] ?? "",
  } as unknown as CSSStyleDeclaration);
  return el;
}

const MOCK_VARS: Record<string, string> = {
  "--accent":    "oklch(0.745 0.130 283)",
  "--warn":      "oklch(0.815 0.155 80)",
  "--crit":      "oklch(0.725 0.195 25)",
  "--info":      "oklch(0.795 0.115 235)",
  "--line":      "oklch(0.275 0.012 250)",
  "--line-2":    "oklch(0.345 0.012 250)",
  "--text":      "oklch(0.965 0.005 250)",
  "--text-2":    "oklch(0.795 0.008 250)",
  "--text-3":    "oklch(0.620 0.010 250)",
  "--surface":   "oklch(0.175 0.012 250)",
  "--surface-2": "oklch(0.205 0.014 250)",
  "--bg":        "oklch(0.145 0.012 250)",
  "--mute":      "oklch(0.500 0.010 250)",
  "--accent-2":  "oklch(0.620 0.140 283)",
  "--accent-ink":"oklch(0.16 0.05 283)",
};

// --------------------------------------------------------------------------
describe("resolveTokens", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("reads all expected token keys from the element", () => {
    const el = makeEl(MOCK_VARS);
    const tokens = resolveTokens(el);

    expect(tokens.accent).toBe("oklch(0.745 0.130 283)");
    expect(tokens.warn).toBe("oklch(0.815 0.155 80)");
    expect(tokens.crit).toBe("oklch(0.725 0.195 25)");
    expect(tokens.info).toBe("oklch(0.795 0.115 235)");
    expect(tokens.line).toBe("oklch(0.275 0.012 250)");
    expect(tokens.line2).toBe("oklch(0.345 0.012 250)");
    expect(tokens.text).toBe("oklch(0.965 0.005 250)");
    expect(tokens.text2).toBe("oklch(0.795 0.008 250)");
    expect(tokens.text3).toBe("oklch(0.620 0.010 250)");
    expect(tokens.surface).toBe("oklch(0.175 0.012 250)");
    expect(tokens.surface2).toBe("oklch(0.205 0.014 250)");
    expect(tokens.bg).toBe("oklch(0.145 0.012 250)");
    expect(tokens.mute).toBe("oklch(0.500 0.010 250)");
    expect(tokens.accent2).toBe("oklch(0.620 0.140 283)");
    expect(tokens.accentInk).toBe("oklch(0.16 0.05 283)");
  });

  it("trims whitespace from CSS var values", () => {
    const el = makeEl({ "--accent": "  oklch(0.745 0.130 283)  " });
    const tokens = resolveTokens(el);
    expect(tokens.accent).toBe("oklch(0.745 0.130 283)");
  });

  it("returns empty string for missing tokens", () => {
    const el = makeEl({});
    const tokens = resolveTokens(el);
    expect(tokens.accent).toBe("");
  });

  it("uses document.documentElement as default element", () => {
    const spy = vi.spyOn(window, "getComputedStyle").mockReturnValue({
      getPropertyValue: (prop: string) => MOCK_VARS[prop.trim()] ?? "",
    } as unknown as CSSStyleDeclaration);

    const tokens = resolveTokens();
    expect(tokens.accent).toBe("oklch(0.745 0.130 283)");
    expect(spy).toHaveBeenCalledWith(document.documentElement);
  });

  it("returns a frozen-shape ThemeTokens object (all required keys present)", () => {
    const el = makeEl(MOCK_VARS);
    const tokens = resolveTokens(el);
    const keys: (keyof ThemeTokens)[] = [
      "accent", "warn", "crit", "info",
      "line", "line2", "text", "text2", "text3",
      "surface", "surface2", "bg", "mute",
      "accent2", "accentInk",
    ];
    for (const k of keys) {
      expect(tokens).toHaveProperty(k);
    }
  });
});

// --------------------------------------------------------------------------
describe("subscribeToThemeChanges", () => {
  afterEach(() => vi.restoreAllMocks());

  it("invokes the callback with fresh tokens when seerflow-theme fires", () => {
    vi.spyOn(window, "getComputedStyle").mockReturnValue({
      getPropertyValue: (prop: string) => MOCK_VARS[prop.trim()] ?? "",
    } as unknown as CSSStyleDeclaration);

    const cb = vi.fn();
    const unsub = subscribeToThemeChanges(cb);

    window.dispatchEvent(new CustomEvent(THEME_EVENT));

    expect(cb).toHaveBeenCalledOnce();
    expect(cb.mock.calls[0][0]).toMatchObject({ accent: "oklch(0.745 0.130 283)" });

    unsub();
  });

  it("does not invoke the callback after unsub", () => {
    vi.spyOn(window, "getComputedStyle").mockReturnValue({
      getPropertyValue: () => "",
    } as unknown as CSSStyleDeclaration);

    const cb = vi.fn();
    const unsub = subscribeToThemeChanges(cb);
    unsub();

    window.dispatchEvent(new CustomEvent(THEME_EVENT));
    expect(cb).not.toHaveBeenCalled();
  });

  it("uses provided element when re-resolving on event", () => {
    const el = document.createElement("div");
    const spy = vi.spyOn(window, "getComputedStyle").mockReturnValue({
      getPropertyValue: (prop: string) => MOCK_VARS[prop.trim()] ?? "",
    } as unknown as CSSStyleDeclaration);

    const cb = vi.fn();
    const unsub = subscribeToThemeChanges(cb, el);
    window.dispatchEvent(new CustomEvent(THEME_EVENT));

    expect(spy).toHaveBeenCalledWith(el);
    unsub();
  });

  it("THEME_EVENT constant equals 'seerflow-theme'", () => {
    expect(THEME_EVENT).toBe("seerflow-theme");
  });
});
