import React from "react";
import { cn } from "@/lib/utils";

export interface LegendItemData {
  color: string;
  label: string;
}

export interface LegendItemProps extends LegendItemData {
  className?: string;
}

/**
 * Single legend entry — 6px color dot + mono label.
 */
export const LegendItem: React.FC<LegendItemProps> = ({ color, label, className }) => (
  <span className={cn("inline-flex items-center gap-1.5", className)}>
    <span
      style={{ width: 6, height: 6, borderRadius: 3, background: color, flexShrink: 0 }}
    />
    <span className="sf-mono text-text-3 text-[10px]">{label}</span>
  </span>
);

export interface LegendProps {
  items: LegendItemData[];
  className?: string;
}

/**
 * Chart legend row — renders multiple LegendItems in a flex row.
 */
export const Legend: React.FC<LegendProps> = ({ items, className }) => (
  <div className={cn("flex items-center gap-4 flex-wrap", className)}>
    {items.map((item) => (
      <LegendItem key={item.label} {...item} />
    ))}
  </div>
);
