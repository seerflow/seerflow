/**
 * resolveTokens — read CSS custom properties from an element and return
 * concrete color strings that canvas APIs (uPlot, Cytoscape) can consume
 * directly (they cannot read CSS vars).
 *
 * Re-resolves on the `seerflow-theme` CustomEvent dispatched by ThemeToggle.
 */

export const THEME_EVENT = "seerflow-theme" as const;

export interface ThemeTokens {
  /** Signature indigo accent */
  accent: string;
  /** Lighter accent variant */
  accent2: string;
  /** Text on accent background */
  accentInk: string;
  /** Amber — anomaly / warning */
  warn: string;
  /** Coral — critical */
  crit: string;
  /** Steel-blue — info */
  info: string;
  /** Hairline border */
  line: string;
  /** Secondary hairline */
  line2: string;
  /** Primary text */
  text: string;
  /** Secondary text */
  text2: string;
  /** Tertiary / muted text */
  text3: string;
  /** Primary surface */
  surface: string;
  /** Secondary surface */
  surface2: string;
  /** Page background */
  bg: string;
  /** Muted / disabled */
  mute: string;
}

const VAR_MAP: Record<keyof ThemeTokens, string> = {
  accent:    "--accent",
  accent2:   "--accent-2",
  accentInk: "--accent-ink",
  warn:      "--warn",
  crit:      "--crit",
  info:      "--info",
  line:      "--line",
  line2:     "--line-2",
  text:      "--text",
  text2:     "--text-2",
  text3:     "--text-3",
  surface:   "--surface",
  surface2:  "--surface-2",
  bg:        "--bg",
  mute:      "--mute",
};

/**
 * Read the current CSS token values from the given element (defaults to
 * `document.documentElement`). Returns a plain object of concrete strings.
 *
 * This is a pure function — call it whenever theme changes.
 */
export function resolveTokens(el: Element = document.documentElement): ThemeTokens {
  const style = getComputedStyle(el);
  const result = {} as ThemeTokens;
  for (const [key, cssVar] of Object.entries(VAR_MAP) as [keyof ThemeTokens, string][]) {
    result[key] = style.getPropertyValue(cssVar).trim();
  }
  return result;
}

/**
 * Subscribe to `seerflow-theme` events and call `cb` with fresh tokens.
 * Returns an unsubscribe function.
 *
 * @example
 *   const unsub = subscribeToThemeChanges((tokens) => uplot.setScale(...))
 *   // cleanup:
 *   unsub()
 */
export function subscribeToThemeChanges(
  cb: (tokens: ThemeTokens) => void,
  el: Element = document.documentElement,
): () => void {
  const handler = () => cb(resolveTokens(el));
  window.addEventListener(THEME_EVENT, handler);
  return () => window.removeEventListener(THEME_EVENT, handler);
}
