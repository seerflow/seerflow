import React from "react";
import { cn } from "@/lib/utils";

export interface SideBlockProps {
  title: string;
  children?: React.ReactNode;
  className?: string;
}

/**
 * Right-inspector section block — mono title with hairline bottom + body.
 * Composes vertically in the right-rail inspector panels (S-318+).
 */
export const SideBlock: React.FC<SideBlockProps> = ({ title, children, className }) => (
  <div className={cn("flex flex-col", className)}>
    <div className="border-b border-line px-4 py-2">
      <span className="sf-mono text-text-3 uppercase tracking-[0.1em] text-[10px]">{title}</span>
    </div>
    <div className="px-4 py-3">{children}</div>
  </div>
);
