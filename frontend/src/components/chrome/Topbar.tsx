import React, { Fragment } from "react";
import { ThemeToggle } from "@/components/brand/ThemeToggle";

export interface TopbarProps {
  /** Breadcrumb segments, e.g. ["Workspace", "Overview"] */
  breadcrumb?: string[];
  /** Called when the user clicks the ⌘K / command-search field */
  onCommandK?: () => void;
}

/**
 * Dashboard topbar.
 * 52px tall; persistent. Breadcrumb left · command search center · controls right.
 */
export const Topbar: React.FC<TopbarProps> = ({
  breadcrumb = ["Workspace", "Overview"],
  onCommandK,
}) => {
  return (
    <div
      style={{
        gridArea: "topbar",
        display: "flex",
        alignItems: "center",
        padding: "0 18px",
        gap: 16,
        borderBottom: "1px solid var(--line)",
        background: "var(--bg)",
        height: 52,
        boxSizing: "border-box",
      }}
    >
      {/* Breadcrumb */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
        {breadcrumb.map((segment, i) => (
          <Fragment key={i}>
            <span
              style={{
                fontSize: 13,
                color:
                  i === breadcrumb.length - 1 ? "var(--text)" : "var(--text-3)",
                fontWeight: i === breadcrumb.length - 1 ? 500 : 400,
              }}
            >
              {segment}
            </span>
            {i < breadcrumb.length - 1 && (
              <span style={{ color: "var(--text-3)" }}>/</span>
            )}
          </Fragment>
        ))}
      </div>

      {/* Command search field */}
      <button
        type="button"
        aria-label="Command search (⌘K)"
        onClick={onCommandK}
        style={{
          flex: 1,
          display: "flex",
          alignItems: "center",
          gap: 8,
          background: "var(--surface)",
          border: "1px solid var(--line)",
          padding: "6px 10px",
          maxWidth: 480,
          margin: "0 auto",
          cursor: "pointer",
          textAlign: "left",
        }}
      >
        <svg
          width={12}
          height={12}
          viewBox="0 0 14 14"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.4"
          style={{ color: "var(--text-3)", flexShrink: 0 }}
          aria-hidden="true"
        >
          <circle cx="6" cy="6" r="4.5" />
          <path d="M10 10l3 3" />
        </svg>
        <span
          style={{
            fontSize: 12.5,
            color: "var(--text-3)",
            flex: 1,
            fontFamily: "var(--font-display)",
          }}
        >
          Jump to entity, rule, event id…
        </span>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10.5,
            color: "var(--text-3)",
            border: "1px solid var(--line)",
            padding: "1px 4px",
          }}
        >
          ⌘K
        </span>
      </button>

      {/* Right controls */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          flexShrink: 0,
        }}
      >
        {/* Time-window selector (static for P0b) */}
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: "var(--text-3)",
          }}
        >
          last 15m
        </span>
        <span style={{ width: 1, height: 16, background: "var(--line)" }} />

        <ThemeToggle size="sm" />

        {/* Notifications bell */}
        <button
          type="button"
          aria-label="Notifications"
          style={{
            background: "transparent",
            border: 0,
            cursor: "pointer",
            color: "var(--text-2)",
            padding: 0,
            display: "flex",
            alignItems: "center",
          }}
        >
          <svg
            width={14}
            height={14}
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M18 8a6 6 0 10-12 0c0 7-3 9-3 9h18s-3-2-3-9M10 22h4" />
          </svg>
        </button>

        {/* User avatar */}
        <div
          data-testid="user-avatar"
          style={{
            width: 24,
            height: 24,
            border: "1px solid var(--line-2)",
            background: "var(--surface-2)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        >
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              color: "var(--text-2)",
            }}
          >
            jt
          </span>
        </div>
      </div>
    </div>
  );
};
