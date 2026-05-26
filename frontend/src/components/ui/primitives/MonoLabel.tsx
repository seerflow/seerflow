import React from "react";
import { cn } from "@/lib/utils";

export interface MonoLabelProps extends React.HTMLAttributes<HTMLSpanElement> {
  /** Rendered as block (div) vs inline-block (span, default). */
  block?: boolean;
}

/**
 * Uppercase mono label — Geist Mono, letter-spaced, `--text-3` muted.
 * Used for section headers, metric names, identifiers.
 */
export const MonoLabel: React.FC<MonoLabelProps> = ({
  className,
  block,
  children,
  ...props
}) => {
  const Comp = block ? "div" : "span";
  return (
    <Comp
      className={cn(
        "sf-mono text-text-3 uppercase tracking-widest text-[11px] font-medium",
        className,
      )}
      {...props}
    >
      {children}
    </Comp>
  );
};
