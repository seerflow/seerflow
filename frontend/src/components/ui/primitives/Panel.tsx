import React from "react";
import { cn } from "@/lib/utils";

export interface PanelProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Remove default padding for custom layout control. */
  noPadding?: boolean;
}

/**
 * Base surface block — `--surface` background, 1px `--line` hairline border, 0 radius.
 * Depth comes from surface steps and hairlines, never shadows.
 */
export const Panel: React.FC<PanelProps> = ({ className, noPadding, children, ...props }) => (
  <div
    className={cn("bg-surface border border-line", !noPadding && "p-4", className)}
    {...props}
  >
    {children}
  </div>
);
