import React, { useEffect, useState } from "react";
import { useThemeStore } from "@/stores/theme";

export interface ThemeToggleProps {
  size?: "sm" | "md";
}

/**
 * Dark/light theme toggle pill.
 * Syncs with the global seerflow-theme event so multiple instances stay consistent.
 * Uses the .sf-light class on <html> (dark default per brand guidelines §3.3).
 */
export const ThemeToggle: React.FC<ThemeToggleProps> = ({ size = "sm" }) => {
  const { theme, toggle } = useThemeStore();
  const [light, setLight] = useState(theme === "light");

  useEffect(() => {
    setLight(theme === "light");
  }, [theme]);

  useEffect(() => {
    const sync = () => setLight(document.documentElement.classList.contains("sf-light"));
    window.addEventListener("seerflow-theme", sync);
    return () => window.removeEventListener("seerflow-theme", sync);
  }, []);

  const dim =
    size === "sm"
      ? { h: 26, pad: 3, ic: 12, fs: 10.5 }
      : { h: 30, pad: 4, ic: 14, fs: 11.5 };

  const switchTo = (toLight: boolean) => {
    if ((toLight && !light) || (!toLight && light)) toggle();
  };

  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: dim.pad,
        height: dim.h,
        boxSizing: "border-box",
        border: "1px solid var(--line)",
        background: "var(--surface)",
      }}
    >
      <button
        onClick={() => switchTo(false)}
        title="Dark"
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          gap: 5,
          padding: "0 8px",
          height: dim.h - dim.pad * 2,
          background: !light ? "var(--surface-2)" : "transparent",
          color: !light ? "var(--text)" : "var(--text-3)",
          border: 0,
          fontFamily: "var(--font-mono)",
          fontSize: dim.fs,
          cursor: "pointer",
          letterSpacing: "0.04em",
        }}
      >
        <svg
          width={dim.ic}
          height={dim.ic}
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path
            d="M13 9.5A5 5 0 116.5 3a4 4 0 006.5 6.5z"
            fill={!light ? "currentColor" : "none"}
            fillOpacity="0.2"
          />
        </svg>
      </button>
      <button
        onClick={() => switchTo(true)}
        title="Light"
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          gap: 5,
          padding: "0 8px",
          height: dim.h - dim.pad * 2,
          background: light ? "var(--surface-2)" : "transparent",
          color: light ? "var(--text)" : "var(--text-3)",
          border: 0,
          fontFamily: "var(--font-mono)",
          fontSize: dim.fs,
          cursor: "pointer",
          letterSpacing: "0.04em",
        }}
      >
        <svg
          width={dim.ic}
          height={dim.ic}
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <circle
            cx="8"
            cy="8"
            r="3"
            fill={light ? "currentColor" : "none"}
            fillOpacity="0.25"
          />
          <path d="M8 1v2M8 13v2M1 8h2M13 8h2M3.2 3.2l1.4 1.4M11.4 11.4l1.4 1.4M3.2 12.8l1.4-1.4M11.4 4.6l1.4-1.4" />
        </svg>
      </button>
    </div>
  );
};
