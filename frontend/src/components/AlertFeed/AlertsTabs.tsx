import type { TabCounts } from "./alertDemo";

export type AlertTab = "open" | "triaging" | "resolved" | "suppressed" | "all";

const TABS: Array<{ key: AlertTab; label: string }> = [
  { key: "open", label: "Open" },
  { key: "triaging", label: "Triaging" },
  { key: "resolved", label: "Resolved" },
  { key: "suppressed", label: "Suppressed" },
  { key: "all", label: "All" },
];

interface Props {
  active: AlertTab;
  counts: TabCounts;
  onSelect: (tab: AlertTab) => void;
}

/**
 * Status tab bar (S-336) — Open / Triaging / Resolved / Suppressed / All with
 * counts and an active underline, ported from the `DashAlertsList` mockup.
 */
export function AlertsTabs({ active, counts, onSelect }: Props): JSX.Element {
  return (
    <div role="tablist" aria-label="alert status" style={{ display: "flex", alignItems: "stretch" }}>
      {TABS.map(({ key, label }) => {
        const isActive = key === active;
        return (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => onSelect(key)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "11px 14px",
              cursor: "pointer",
              color: isActive ? "var(--text)" : "var(--text-2)",
              // Reset top/left/right borders first, then declare the bottom edge
              // last so the active underline (2px accent) is the single source
              // of truth — a trailing `border: none` would otherwise clobber it.
              background: "transparent",
              borderTop: "none",
              borderLeft: "none",
              borderRight: "none",
              borderBottom: isActive ? "2px solid var(--accent)" : "2px solid transparent",
              marginBottom: -1,
              fontFamily: "var(--font-display)",
            }}
          >
            <span style={{ fontSize: 13, fontWeight: isActive ? 500 : 400 }}>{label}</span>
            <span
              className="sf-mono sf-tnum"
              style={{
                fontSize: 10.5,
                color: "var(--text-3)",
                border: "1px solid var(--line)",
                padding: "1px 5px",
              }}
            >
              {counts[key]}
            </span>
          </button>
        );
      })}
    </div>
  );
}
