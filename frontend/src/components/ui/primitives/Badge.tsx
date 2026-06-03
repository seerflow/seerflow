import React from "react";
import { cn } from "@/lib/utils";

export type SFBadgeVariant = "accent" | "warn" | "crit" | "info" | "mute";

const VARIANT_CLASSES: Record<SFBadgeVariant, string> = {
  accent: "text-accent border-[color-mix(in_oklch,var(--accent)_35%,transparent)] bg-[color-mix(in_oklch,var(--accent)_12%,transparent)]",
  warn:   "text-warn   border-[color-mix(in_oklch,var(--warn)_35%,transparent)]   bg-[color-mix(in_oklch,var(--warn)_12%,transparent)]",
  crit:   "text-crit   border-[color-mix(in_oklch,var(--crit)_35%,transparent)]   bg-[color-mix(in_oklch,var(--crit)_12%,transparent)]",
  info:   "text-info   border-[color-mix(in_oklch,var(--info)_35%,transparent)]   bg-[color-mix(in_oklch,var(--info)_12%,transparent)]",
  mute:   "text-text-3 border-line bg-surface-2",
};

export interface SFBadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: SFBadgeVariant;
}

/**
 * Design-system badge — color-mix tint + hairline border.
 * Accent ≤ 5% principle: badges are the smallest accent surface.
 * Named SFBadge to avoid collision with the existing shadcn Badge component.
 */
export const SFBadge: React.FC<SFBadgeProps> = ({
  variant = "accent",
  className,
  children,
  ...props
}) => (
  <span
    className={cn(
      "sf-mono inline-flex items-center border px-[5px] py-[1px] text-[10px] font-medium leading-none",
      VARIANT_CLASSES[variant],
      className,
    )}
    {...props}
  >
    {children}
  </span>
);
