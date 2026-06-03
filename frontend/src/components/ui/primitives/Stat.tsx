import React from "react";
import { cn } from "@/lib/utils";

export interface StatProps {
  label: string;
  value: React.ReactNode;
  delta?: string;
  /** Optional sparkline or chart rendered below the value row. */
  children?: React.ReactNode;
  className?: string;
}

/**
 * KPI stat block — mono label + large tnum value + optional delta + sparkline slot.
 * Used in the Overview KPI strip and similar metric displays.
 */
export const Stat: React.FC<StatProps> = ({ label, value, delta, children, className }) => (
  <div className={cn("flex flex-col gap-1", className)}>
    <span className="sf-mono text-text-3 uppercase tracking-[0.1em] text-[10px]">{label}</span>
    <div className="flex items-baseline gap-2">
      <span className="sf-tnum text-[26px] font-semibold tracking-[-0.025em] leading-none">
        {value}
      </span>
      {delta !== undefined && (
        <span className="sf-mono sf-tnum text-[11px] text-text-3">{delta}</span>
      )}
    </div>
    {children && <div className="mt-1">{children}</div>}
  </div>
);
