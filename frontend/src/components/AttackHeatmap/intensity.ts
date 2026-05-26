import type React from "react";

export type Intensity = "none" | "min" | "low" | "warn" | "crit";

export function intensityLevel(
  covered: boolean,
  detected: boolean,
  ruleCount: number,
  alertCount: number,
): Intensity {
  if (detected && alertCount > 0) return "crit";
  if (detected) return "warn";
  if (covered && ruleCount > 1) return "low";
  if (covered) return "min";
  return "none";
}

export const INTENSITY_STYLE: Record<Intensity, React.CSSProperties> = {
  none: {
    background: "var(--surface-2)",
    border: "1px solid var(--line)",
  },
  min: {
    background: "color-mix(in oklch, var(--accent) 22%, transparent)",
    border: "1px solid color-mix(in oklch, var(--accent) 20%, transparent)",
  },
  low: {
    background: "color-mix(in oklch, var(--accent) 55%, transparent)",
    border: "1px solid color-mix(in oklch, var(--accent) 30%, transparent)",
  },
  warn: {
    background: "var(--warn)",
    border: "1px solid color-mix(in oklch, var(--warn) 40%, transparent)",
  },
  crit: {
    background: "var(--crit)",
    border: "1px solid color-mix(in oklch, var(--crit) 40%, transparent)",
  },
};

export const INTENSITY_SWATCHES: { level: Intensity; label: string }[] = [
  { level: "none", label: "none" },
  { level: "min",  label: "min" },
  { level: "low",  label: "low" },
  { level: "warn", label: "warn" },
  { level: "crit", label: "crit" },
];
