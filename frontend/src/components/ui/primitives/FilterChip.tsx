import React from "react";
import { cn } from "@/lib/utils";

export interface FilterChipProps {
  label: string;
  active: boolean;
  onClick?: () => void;
  className?: string;
}

/**
 * Toggle chip for filter rails — active = accent border + text; inactive = muted.
 * Used in entity graph type filters, layout toggles, sigma rule type filters.
 */
export const FilterChip: React.FC<FilterChipProps> = ({ label, active, onClick, className }) => (
  <button
    onClick={onClick}
    className={cn(
      "sf-mono border px-2 py-1 text-[11px] leading-none cursor-pointer transition-colors",
      active
        ? "border-accent text-accent bg-[color-mix(in_oklch,var(--accent)_8%,transparent)]"
        : "border-line text-text-3 hover:border-line-2 hover:text-text-2",
      className,
    )}
  >
    {label}
  </button>
);

export interface FilterRowProps {
  children: React.ReactNode;
  className?: string;
}

/**
 * Horizontal row of FilterChips with consistent gap.
 */
export const FilterRow: React.FC<FilterRowProps> = ({ children, className }) => (
  <div className={cn("flex items-center gap-1.5 flex-wrap", className)}>{children}</div>
);
