import React from "react";

// The SeerMark SVG uses a viewBox of 198x117 (≈ 1.69:1 aspect ratio).
// Width is derived from the rendered height to preserve the aspect ratio.
const SF_MARK_ASPECT = 198 / 117;

export type SeerMarkVariant = "color" | "dark" | "mono-black" | "mono-white";

const VARIANT_SRCS: Record<SeerMarkVariant, string> = {
  color:        new URL("../../assets/brand/seerflow_logo_color.svg", import.meta.url).href,
  dark:         new URL("../../assets/brand/seerflow_logo_dark.svg", import.meta.url).href,
  "mono-black": new URL("../../assets/brand/seerflow_logo_mono_black.svg", import.meta.url).href,
  "mono-white": new URL("../../assets/brand/seerflow_logo_mono_white.svg", import.meta.url).href,
};

export interface SeerMarkProps {
  /** Rendered height in px — width is derived from the 198/117 aspect ratio. */
  size?: number;
  /**
   * Color variant.
   * - color: indigo body + cyan iris (default, use on dark bg)
   * - dark: suitable for light backgrounds
   * - mono-black / mono-white: single-ink variants
   *
   * The mark is NEVER tinted by the runtime --accent. It is always the brand mark.
   */
  variant?: SeerMarkVariant;
  className?: string;
}

/**
 * Official Seerflow brand mark.
 * The mark stays indigo+cyan regardless of the current accent token.
 * Minimum sizes: 20px UI, 32px nav (per brand guidelines §3.5).
 */
export const SeerMark: React.FC<SeerMarkProps> = ({
  size = 28,
  variant = "color",
  className,
}) => {
  const w = Math.round(size * SF_MARK_ASPECT);
  return (
    <img
      src={VARIANT_SRCS[variant]}
      width={w}
      height={size}
      alt=""
      aria-hidden="true"
      draggable={false}
      style={{ display: "block", flexShrink: 0 }}
      className={className}
    />
  );
};
