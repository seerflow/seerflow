import React from "react";
import { cn } from "@/lib/utils";

export type RiskLevel = "crit" | "warn" | "accent" | "mute";

/** Derive risk level from a 0–1 value using thresholds from the mockup spec. */
export function riskLevelFromValue(value: number): RiskLevel {
  if (value >= 0.8) return "crit";
  if (value >= 0.6) return "warn";
  if (value >= 0.4) return "accent";
  return "mute";
}

const FILL_COLORS: Record<RiskLevel, string> = {
  crit:   "var(--crit)",
  warn:   "var(--warn)",
  accent: "var(--accent)",
  mute:   "var(--mute)",
};

export interface RiskBarProps {
  /** Risk score 0–1. */
  value: number;
  /** Override automatic level derivation. */
  level?: RiskLevel;
  /** Track height in px. Default 3 (per spec). */
  height?: number;
  className?: string;
}

/**
 * 3px-high risk score bar — color by threshold (crit/warn/accent/mute).
 * Track is `--surface-2`; fill is the semantic color token.
 * No rounded corners (0-radius per §3.7 "sharp geometry").
 */
export const RiskBar: React.FC<RiskBarProps> = ({
  value,
  level,
  height = 3,
  className,
}) => {
  const resolvedLevel = level ?? riskLevelFromValue(value);
  const pct = Math.min(100, Math.max(0, value * 100));

  return (
    <div
      className={cn("relative w-full bg-surface-2 overflow-hidden", className)}
      style={{ height: `${height}px` }}
    >
      <div
        className={cn(
          resolvedLevel === "crit"   && "bg-crit",
          resolvedLevel === "warn"   && "bg-warn",
          resolvedLevel === "accent" && "bg-accent",
          resolvedLevel === "mute"   && "bg-mute",
          "absolute inset-y-0 left-0",
        )}
        style={{
          width: `${pct}%`,
          backgroundColor: FILL_COLORS[resolvedLevel],
        }}
      />
    </div>
  );
};
