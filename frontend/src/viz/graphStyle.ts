/**
 * Cytoscape stylesheet builder for the entity graph — maps resolved theme
 * tokens to a Cytoscape style array. Kept in its own module (no React export)
 * so it can be unit-tested directly and so the canvas component stays
 * fast-refresh friendly.
 */
import { riskToColor } from "./entityGraphAdapter";
import type { resolveTokens } from "@/lib/theme/resolveTokens";

// Canvas-safe monospace stack. Cytoscape renders labels to <canvas>, which
// cannot resolve CSS custom properties — `var(--font-mono)` silently fell back
// to the browser default. Mirror the --font-mono stack with concrete names.
const LABEL_FONT_FAMILY = '"Geist Mono", ui-monospace, SFMono-Regular, Menlo, monospace';

export function buildStyle(tokens: ReturnType<typeof resolveTokens>) {
  return [
    {
      selector: "node",
      style: {
        "background-color": (ele: { data: (k: string) => number }) =>
          riskToColor(ele.data("riskScore") ?? 0, tokens),
        "border-color": (ele: { data: (k: string) => number }) =>
          riskToColor(ele.data("riskScore") ?? 0, tokens),
        "border-width": 1,
        "width": (ele: { data: (k: string) => number }) => ele.data("size") ?? 12,
        "height": (ele: { data: (k: string) => number }) => ele.data("size") ?? 12,
        "label": (ele: { data: (k: string) => string }) => ele.data("label") ?? "",
        "font-size": 9,
        "font-family": LABEL_FONT_FAMILY,
        // High-contrast label text with a background-colored halo so names stay
        // legible over edges and against dark/light canvas alike.
        "color": tokens.text,
        "text-outline-color": tokens.bg,
        "text-outline-width": 1,
        "text-valign": "bottom" as const,
        "text-margin-y": 4,
        "opacity": 0.9,
      },
    },
    {
      selector: "node:selected",
      style: {
        "border-color": tokens.crit,
        "border-width": 2,
        "border-style": "dashed" as const,
      },
    },
    {
      selector: "edge",
      style: {
        "line-color": tokens.line2,
        "width": 1,
        "opacity": 0.6,
        "curve-style": "bezier" as const,
      },
    },
    {
      selector: "edge[severity > 0.6]",
      style: {
        "line-color": tokens.warn,
        "width": 1.5,
        "opacity": 0.8,
      },
    },
    {
      selector: "edge[severity > 0.8]",
      style: {
        "line-color": tokens.crit,
        "width": 2,
        "opacity": 0.9,
      },
    },
  ];
}
