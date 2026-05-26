import React from "react";
import { SeerMark } from "@/components/brand/SeerMark";

export interface ScreenStubProps {
  label: string;
}

/**
 * Branded placeholder for screens not yet implemented.
 * Displays the Seerflow mark, the screen label, and a "coming soon" notice.
 * Later stories replace the contents of the screen file — this component
 * stays as the seam until then.
 */
export const ScreenStub: React.FC<ScreenStubProps> = ({ label }) => {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        height: "100%",
        gap: 20,
        background: "var(--bg)",
        color: "var(--text-3)",
      }}
    >
      <SeerMark size={32} variant="color" />
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "var(--text-3)",
          }}
        >
          {label}
        </span>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 13,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: "var(--text-2)",
            fontWeight: 600,
          }}
        >
          Coming soon
        </span>
        <span style={{ fontSize: 13, color: "var(--text-3)", marginTop: 4 }}>
          This screen is under construction.
        </span>
      </div>
    </div>
  );
};
