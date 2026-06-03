import React from "react";
import { cn } from "@/lib/utils";

export type EntityType = "user" | "host" | "ip" | "service" | "process";

/** Icon SVG paths from the mockup vocabulary (dashboard.jsx primitive inventory). */
const ENTITY_PATHS: Record<EntityType, string> = {
  user:    "M12 12a4 4 0 100-8 4 4 0 000 8zM4 20c0-3.314 3.582-6 8-6s8 2.686 8 6",
  host:    "M3 6h18v12H3zM8 6V4M16 6V4M3 10h18",
  ip:      "M12 2a10 10 0 100 20A10 10 0 0012 2zM2 12h20M12 2c-2.5 3-4 6.5-4 10s1.5 7 4 10M12 2c2.5 3 4 6.5 4 10s-1.5 7-4 10",
  service: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14l3 3 3-3M17 17v-4",
  process: "M3 3h6l2 2h7v14H3zM12 12l2-2M14 12h-2v2",
};

export interface EntityGlyphProps {
  type: EntityType;
  /** Box size in px (both width and height). Default 24. */
  size?: number;
  className?: string;
}

/**
 * 24px hairline-boxed entity type icon — user/host/ip/service/process.
 * Used inline in lists, table rows, and graph node labels.
 */
export const EntityGlyph: React.FC<EntityGlyphProps> = ({ type, size = 24, className }) => (
  <span
    className={cn("inline-flex items-center justify-center border border-line flex-shrink-0", className)}
    style={{ width: `${size}px`, height: `${size}px` }}
  >
    <svg
      width={Math.round(size * 0.6)}
      height={Math.round(size * 0.6)}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ color: "var(--text-2)" }}
    >
      <path d={ENTITY_PATHS[type]} />
    </svg>
  </span>
);
