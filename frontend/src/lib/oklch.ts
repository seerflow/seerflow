/**
 * OKLCH → sRGB hex conversion.
 *
 * The seerflow brand tokens are authored in OKLCH. Some canvas consumers reject
 * `oklch(...)` color strings (Monaco's theme parser throws; Cytoscape's style
 * parser silently ignores them and falls back to defaults), so colors handed to
 * those engines must be concrete hex. This is the single shared implementation
 * used by both the Monaco theme (S-343/S-344) and the entity-graph stylesheet.
 */

/**
 * Convert an `oklch(L C h)` string to a 6-digit sRGB hex.
 *
 * Implements the standard OKLCH → OKLab → linear-sRGB → gamma-encoded sRGB
 * pipeline (Björn Ottosson, https://bottosson.github.io/posts/oklab/). Returns
 * `null` on parse failure so the caller can fall back to a hard-coded hex.
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

const HEX_RE = /^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/;

/**
 * Coerce any CSS color token to a canvas-safe color string. Hex passes through
 * unchanged; `oklch(...)` is converted to hex; anything else (rgb/named/empty)
 * is returned as-is for the caller to handle or fall back on.
 */
export function toCanvasColor(value: string): string {
  if (!value) return value;
  if (HEX_RE.test(value)) return value;
  if (value.toLowerCase().startsWith("oklch(")) {
    return oklchToHex(value) ?? value;
  }
  return value;
}
