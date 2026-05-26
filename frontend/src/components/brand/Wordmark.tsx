import React from "react";
import { SeerMark, SeerMarkVariant } from "./SeerMark";

export interface WordmarkProps {
  /** Text size in px — mark height is 1.55x text size (matches mockup ratio). */
  size?: number;
  /** Whether to include the SeerMark logo. */
  mark?: boolean;
  /** Color variant forwarded to SeerMark. */
  variant?: SeerMarkVariant;
  /** Gap between mark and wordmark text (px). */
  gap?: number;
  className?: string;
}

/**
 * Seerflow horizontal wordmark — mark + "seerflow" in Geist Mono.
 * The mark stays indigo+cyan regardless of the runtime accent.
 */
export const Wordmark: React.FC<WordmarkProps> = ({
  size = 18,
  mark = true,
  variant = "color",
  gap = 10,
  className,
}) => (
  <span
    style={{ display: "inline-flex", alignItems: "center", gap, lineHeight: 1 }}
    className={className}
  >
    {mark && <SeerMark size={Math.round(size * 1.55)} variant={variant} />}
    <span
      className="sf-mono"
      style={{ fontWeight: 700, fontSize: size, letterSpacing: "-0.01em" }}
    >
      seerflow
    </span>
  </span>
);
