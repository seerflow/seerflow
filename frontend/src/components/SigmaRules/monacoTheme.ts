/**
 * S-324: Monaco editor theme derived from the seerflow OKLCH token palette.
 *
 * resolveTokens() reads the CSS custom properties at runtime (so the values
 * respect light/dark mode). Hex fallbacks match the dark-mode token values
 * so the theme works even in test environments where CSS vars aren't applied.
 *
 * buildMonacoTheme() produces a MonacoThemeData-compatible object for
 * monaco.editor.defineTheme / monaco.editor.setTheme calls.
 *
 * SEERFLOW_MONACO_THEME is the string key to pass to those calls.
 */

export interface SeerflowTokenMap {
  bg: string;
  surface: string;
  surface2: string;
  text: string;
  text2: string;
  text3: string;
  accent: string;
  accent2: string;
  line: string;
  crit: string;
  warn: string;
}

/** Dark-mode hex fallbacks matching the seerflow OKLCH palette. */
const FALLBACKS: SeerflowTokenMap = {
  bg:       "#0d0d0d",
  surface:  "#141414",
  surface2: "#1a1a1a",
  text:     "#e8e8e8",
  text2:    "#a8a8a8",
  text3:    "#525252",
  accent:   "#7c9ef8",
  accent2:  "#9de0c8",
  line:     "#222222",
  crit:     "#f87272",
  warn:     "#f8c572",
};

const CSS_VAR_MAP: Record<keyof SeerflowTokenMap, string> = {
  bg:       "--bg",
  surface:  "--surface",
  surface2: "--surface-2",
  text:     "--text",
  text2:    "--text-2",
  text3:    "--text-3",
  accent:   "--accent",
  accent2:  "--accent-2",
  line:     "--line",
  crit:     "--crit",
  warn:     "--warn",
};

function readCssVar(name: string): string | null {
  if (typeof window === "undefined" || typeof document === "undefined") return null;
  const val = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return val || null;
}

/**
 * Monaco's theme parser only accepts hex colors (`#rgb`, `#rrggbb`, `#rrggbbaa`)
 * for token foregrounds — feeding it `oklch(...)` / `rgb(...)` / named colors
 * throws `Illegal value for token color: ...` from `setTheme`, which then
 * unmounts the whole React tree (blank screen). The seerflow brand tokens are
 * OKLCH, so the live computed CSS-var values are NOT Monaco-safe out of the
 * box; we either pass them straight through (already-hex) or convert them.
 */
const HEX_RE = /^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/;

function isMonacoHex(v: string): boolean {
  return HEX_RE.test(v);
}

/**
 * Convert an `oklch(L C h)` string to a 6-digit sRGB hex.
 *
 * Implements the standard OKLCH → OKLab → linear-sRGB → gamma-encoded sRGB
 * pipeline (Björn Ottosson, https://bottosson.github.io/posts/oklab/). Returns
 * `null` on parse failure so the caller can fall back to a hard-coded hex.
 *
 * Why this exists: S-343 hex-only fallback worked but the `FALLBACKS` constants
 * did not match the seerflow brand OKLCH palette (e.g. `--accent` is violet
 * `oklch(0.745 0.130 283)` but the fallback was indigo `#7c9ef8`). The YAML
 * editor rendered in the wrong palette. Converting the live brand value keeps
 * Monaco visually consistent with the rest of the (OKLCH) app.
 */
export function oklchToHex(value: string): string | null {
  const m = value.trim().match(
    /^oklch\(\s*([0-9]*\.?[0-9]+%?)\s+([0-9]*\.?[0-9]+%?)\s+([0-9]*\.?[0-9]+)\s*\)$/i,
  );
  if (!m) return null;

  const parsePct = (s: string, fullScale: number): number =>
    s.endsWith("%") ? (parseFloat(s) / 100) * fullScale : parseFloat(s);

  const L = parsePct(m[1], 1); // L expressed as 0..1 or 0..100%
  const C = parsePct(m[2], 0.4); // C: 0..0.4 or 0..100% (100% == 0.4)
  const h = (parseFloat(m[3]) * Math.PI) / 180;

  const a = C * Math.cos(h);
  const b = C * Math.sin(h);

  // OKLab → linear sRGB.
  const l_ = L + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = L - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = L - 0.0894841775 * a - 1.291485548 * b;

  const lRaw = l_ * l_ * l_;
  const mRaw = m_ * m_ * m_;
  const sRaw = s_ * s_ * s_;

  const rLin = 4.0767416621 * lRaw - 3.3077115913 * mRaw + 0.2309699292 * sRaw;
  const gLin = -1.2684380046 * lRaw + 2.6097574011 * mRaw - 0.3413193965 * sRaw;
  const bLin = -0.0041960863 * lRaw - 0.7034186147 * mRaw + 1.707614701 * sRaw;

  // Gamma-encode (sRGB transfer).
  const enc = (v: number): number =>
    v <= 0.0031308 ? 12.92 * v : 1.055 * Math.pow(v, 1 / 2.4) - 0.055;
  const clamp01 = (v: number): number => Math.max(0, Math.min(1, v));
  const toByte = (v: number): number => Math.round(clamp01(enc(v)) * 255);

  const R = toByte(rLin);
  const G = toByte(gLin);
  const B = toByte(bLin);

  const hex2 = (n: number): string => n.toString(16).padStart(2, "0");
  return `#${hex2(R)}${hex2(G)}${hex2(B)}`;
}

/**
 * Resolves the seerflow design token map for Monaco.
 *
 * Resolution order per token:
 * 1. Live CSS-var value if it's already a Monaco-safe hex literal.
 * 2. Live CSS-var value if it's `oklch(...)` — convert to hex via
 *    {@link oklchToHex} so Monaco gets the live brand colour exactly.
 * 3. The hard-coded hex constant in `FALLBACKS` (SSR / jsdom / unparseable).
 */
export function resolveTokens(): SeerflowTokenMap {
  const result = {} as SeerflowTokenMap;
  for (const key of Object.keys(FALLBACKS) as Array<keyof SeerflowTokenMap>) {
    const cssVal = readCssVar(CSS_VAR_MAP[key]);
    let resolved: string | null = null;
    if (cssVal) {
      if (isMonacoHex(cssVal)) {
        resolved = cssVal;
      } else if (cssVal.toLowerCase().startsWith("oklch(")) {
        resolved = oklchToHex(cssVal);
      }
    }
    result[key] = resolved ?? FALLBACKS[key];
  }
  return result;
}

export interface MonacoThemeRule {
  token: string;
  foreground?: string;
  background?: string;
  fontStyle?: string;
}

export interface MonacoThemeColors {
  [key: string]: string;
}

export interface MonacoThemeData {
  base: "vs" | "vs-dark" | "hc-black" | "hc-light";
  inherit: boolean;
  rules: MonacoThemeRule[];
  colors: MonacoThemeColors;
}

/**
 * Builds a Monaco theme object from the resolved token map.
 * Strips leading '#' from hex values since Monaco colors don't use the '#' prefix.
 */
export function buildMonacoTheme(): MonacoThemeData {
  const t = resolveTokens();

  const hex = (v: string) => v.replace(/^#/, "");

  return {
    base: "vs-dark",
    inherit: false,
    rules: [
      // YAML tokens
      { token: "key.yaml",           foreground: hex(t.accent),  fontStyle: "" },
      { token: "string.yaml",        foreground: hex(t.accent2), fontStyle: "" },
      { token: "comment",            foreground: hex(t.text3),   fontStyle: "italic" },
      { token: "number",             foreground: hex(t.warn),    fontStyle: "" },
      { token: "keyword",            foreground: hex(t.crit),    fontStyle: "" },
      { token: "type",               foreground: hex(t.text2),   fontStyle: "" },
      { token: "delimiter",          foreground: hex(t.text3),   fontStyle: "" },
      { token: "",                   foreground: hex(t.text),    fontStyle: "" },
    ],
    colors: {
      "editor.background":               t.surface,
      "editor.foreground":               t.text,
      "editor.lineHighlightBackground":  t.surface2,
      "editor.selectionBackground":      `${hex(t.accent)}33`,
      "editorLineNumber.foreground":     t.text3,
      "editorLineNumber.activeForeground": t.text2,
      "editorCursor.foreground":         t.accent,
      "editor.inactiveSelectionBackground": `${hex(t.accent)}1a`,
      "editorWhitespace.foreground":     t.text3,
      "editorIndentGuide.background1":   t.line,
      "editorIndentGuide.activeBackground1": t.text3,
      "scrollbar.shadow":                t.bg,
      "scrollbarSlider.background":      `${hex(t.text3)}40`,
      "scrollbarSlider.hoverBackground": `${hex(t.text2)}40`,
      "scrollbarSlider.activeBackground": `${hex(t.text)}40`,
    },
  };
}

/** Theme name to pass to monaco.editor.defineTheme / setTheme. */
export const SEERFLOW_MONACO_THEME = "seerflow-dark";
