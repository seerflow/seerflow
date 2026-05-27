import type { CSSProperties, ReactNode } from "react";
import type { AlertStatus } from "./alertDemo";

/**
 * Small presentational pieces for the alert SOC console (S-336), ported from
 * the `DashAlertsList` mockup (docs/new_image/dashboard.jsx). Styling follows
 * the EventStream (S-325/S-335) convention: CSS-var inline styles, no Tailwind.
 * Interactive elements are real <button>s for accessibility.
 */

export function SummaryStat({
  label,
  value,
  tone = "text-2",
}: {
  label: string;
  value: string;
  tone?: "crit" | "warn" | "text-2";
}): JSX.Element {
  const color = tone === "crit" ? "var(--crit)" : tone === "warn" ? "var(--warn)" : "var(--text-2)";
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
      <span
        className="sf-tnum"
        style={{ fontSize: 18, fontWeight: 600, letterSpacing: "-0.02em", color }}
      >
        {value}
      </span>
      <span
        className="sf-mono"
        style={{
          fontSize: 10.5,
          color: "var(--text-3)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
        }}
      >
        {label}
      </span>
    </div>
  );
}

export function TBtn({
  children,
  primary,
  onClick,
}: {
  children: ReactNode;
  primary?: boolean;
  onClick?: () => void;
}): JSX.Element {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        fontSize: 12,
        fontWeight: 500,
        padding: "6px 12px",
        border: "1px solid " + (primary ? "var(--accent)" : "var(--line)"),
        background: primary ? "var(--accent)" : "var(--surface)",
        color: primary ? "var(--bg)" : "var(--text-2)",
        cursor: "pointer",
        whiteSpace: "nowrap",
        fontFamily: "var(--font-display)",
      }}
    >
      {children}
    </button>
  );
}

export function AlertsFilterChip({
  label,
  value,
  placeholder,
}: {
  label: string;
  value: string;
  placeholder?: string;
}): JSX.Element {
  const empty = !value;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "5px 10px",
        border: "1px dashed " + (empty ? "var(--line-2)" : "var(--line)"),
        background: empty ? "transparent" : "var(--surface)",
        cursor: "pointer",
      }}
    >
      <span
        className="sf-mono"
        style={{
          fontSize: 10.5,
          color: "var(--text-3)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
        }}
      >
        {label}
      </span>
      <span style={{ fontSize: 12, color: empty ? "var(--text-3)" : "var(--text-2)" }}>
        {empty ? placeholder || "+" : value}
      </span>
      {!empty && (
        <svg width="9" height="9" viewBox="0 0 10 10" fill="none" stroke="var(--text-3)" strokeWidth="1.4">
          <path d="M2.5 4l2.5 2.5 2.5-2.5" />
        </svg>
      )}
    </span>
  );
}

const STATUS_STYLE: Record<AlertStatus, { color: string; bg: string; border: string }> = {
  open: {
    color: "var(--crit)",
    bg: "color-mix(in oklch, var(--crit) 12%, transparent)",
    border: "color-mix(in oklch, var(--crit) 35%, transparent)",
  },
  triaging: {
    color: "var(--warn)",
    bg: "color-mix(in oklch, var(--warn) 12%, transparent)",
    border: "color-mix(in oklch, var(--warn) 35%, transparent)",
  },
  resolved: { color: "var(--text-3)", bg: "transparent", border: "var(--line)" },
  suppressed: { color: "var(--text-3)", bg: "transparent", border: "var(--line)" },
};

export function StatusPill({ status }: { status: AlertStatus }): JSX.Element {
  const s = STATUS_STYLE[status] ?? STATUS_STYLE.resolved;
  return (
    <span
      className="sf-mono"
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        fontSize: 10.5,
        padding: "2px 7px",
        color: s.color,
        background: s.bg,
        border: "1px solid " + s.border,
        letterSpacing: "0.06em",
        textTransform: "uppercase",
      }}
    >
      <span style={{ width: 5, height: 5, background: s.color }} aria-hidden />
      {status}
    </span>
  );
}

const ENTITY_ICONS: Record<string, JSX.Element> = {
  user: (
    <>
      <circle cx="6" cy="4.5" r="2" />
      <path d="M2 11c0-2 1.5-3.5 4-3.5s4 1.5 4 3.5" />
    </>
  ),
  host: (
    <>
      <rect x="2" y="3" width="8" height="6" />
      <path d="M4 11h4M5 9v2" />
    </>
  ),
  service: <path d="M6 1.5l4 2.5v3.5l-4 2.5-4-2.5V4z" />,
  ip: (
    <>
      <circle cx="6" cy="6" r="4.5" />
      <path d="M1.5 6h9M6 1.5c1.5 1.8 1.5 7.2 0 9M6 1.5c-1.5 1.8-1.5 7.2 0 9" />
    </>
  ),
  process: (
    <>
      <rect x="1.5" y="1.5" width="9" height="9" />
      <path d="M3.5 4.5h5M3.5 6.5h3.5M3.5 8.5h4" />
    </>
  ),
};

export function MiniEntityIcon({ kind }: { kind: string }): JSX.Element {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill="none"
      stroke="var(--text-2)"
      strokeWidth="1.1"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {ENTITY_ICONS[kind] ?? ENTITY_ICONS.host}
    </svg>
  );
}

export function PageBtn({
  children,
  active,
  disabled,
  onClick,
}: {
  children: ReactNode;
  active?: boolean;
  disabled?: boolean;
  onClick?: () => void;
}): JSX.Element {
  const style: CSSProperties = {
    fontSize: 11,
    minWidth: 22,
    padding: "3px 6px",
    textAlign: "center",
    border: "1px solid var(--line)",
    color: active ? "var(--text)" : "var(--text-2)",
    background: active ? "var(--surface-2)" : "transparent",
    cursor: disabled ? "default" : "pointer",
    opacity: disabled ? 0.4 : 1,
  };
  return (
    <button
      type="button"
      className="sf-mono sf-tnum"
      aria-current={active ? "page" : undefined}
      disabled={disabled}
      onClick={onClick}
      style={style}
    >
      {children}
    </button>
  );
}
