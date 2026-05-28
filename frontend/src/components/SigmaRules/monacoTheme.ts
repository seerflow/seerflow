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
 * OKLCH, so the live computed CSS-var values are NOT Monaco-safe; the value is
 * only usable when it happens to be a hex literal.
 */
const HEX_RE = /^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/;

function isMonacoHex(v: string): boolean {
  return HEX_RE.test(v);
}

/**
 * Resolves the seerflow design token map for Monaco.
 *
 * Prefers the live CSS custom-property value ONLY when it is a Monaco-safe
 * hex literal; otherwise falls back to the hard-coded hex constants in
 * `FALLBACKS`. This covers (a) SSR / test environments with no CSS, (b) the
 * brand-default OKLCH values which Monaco rejects, and (c) any future
 * `rgb()` / named color drift that would also crash Monaco.
 */
export function resolveTokens(): SeerflowTokenMap {
  const result = {} as SeerflowTokenMap;
  for (const key of Object.keys(FALLBACKS) as Array<keyof SeerflowTokenMap>) {
    const cssVal = readCssVar(CSS_VAR_MAP[key]);
    result[key] = cssVal && isMonacoHex(cssVal) ? cssVal : FALLBACKS[key];
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
