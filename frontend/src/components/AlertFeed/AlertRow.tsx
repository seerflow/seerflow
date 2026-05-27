import { memo } from "react";
import type { Alert } from "@/lib/types";
import { severityBucket } from "@/lib/severity";
import { StatusPill, MiniEntityIcon } from "./AlertConsoleParts";
import { deriveOwner, deriveStatus, entityChips, compactUpdated } from "./alertDemo";

export const ALERT_GRID = "32px 70px 1.6fr 1.3fr 64px 90px 70px 56px";

interface Props {
  alert: Alert;
  selected: boolean;
  onOpen: (id: string) => void;
}

function sevDisplay(severity: number): { color: string; label: string } {
  const bucket = severityBucket(severity);
  if (bucket === "critical") return { color: "var(--crit)", label: "CRIT" };
  if (bucket === "high") return { color: "var(--warn)", label: "WARN" };
  if (bucket === "medium") return { color: "var(--warn)", label: "WARN" };
  return { color: "var(--text-3)", label: "INFO" };
}

function Row({ alert, selected, onOpen }: Props): JSX.Element {
  const sev = sevDisplay(alert.severity);
  const status = deriveStatus(alert);
  const owner = deriveOwner(alert.alert_id);
  const chips = entityChips(alert);
  const tactics = alert.mitre_tactics.length;

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`alert ${alert.rule_name}`}
      onClick={() => onOpen(alert.alert_id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen(alert.alert_id);
        }
      }}
      style={{
        display: "grid",
        gridTemplateColumns: ALERT_GRID,
        alignItems: "center",
        gap: 14,
        padding: "11px 28px",
        paddingLeft: 26,
        borderBottom: "1px solid var(--line)",
        background: selected ? "color-mix(in oklch, var(--accent) 6%, transparent)" : "transparent",
        borderLeft: selected ? "2px solid var(--accent)" : "2px solid transparent",
        cursor: "pointer",
      }}
    >
      {/* Checkbox — selection is decorative in the demo (row click navigates) */}
      <input
        type="checkbox"
        checked={selected}
        readOnly
        aria-hidden
        tabIndex={-1}
        style={{ accentColor: "var(--accent)" }}
        onClick={(e) => e.stopPropagation()}
      />

      {/* Sev · Score */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ width: 6, height: 6, background: sev.color, flexShrink: 0 }} aria-hidden />
        <span className="sf-mono sf-tnum" style={{ fontSize: 11.5, color: sev.color, letterSpacing: "0.04em" }}>
          {sev.label}
        </span>
        <span className="sf-mono sf-tnum" style={{ fontSize: 11.5, color: "var(--text-2)" }}>
          {alert.risk_score.toFixed(2)}
        </span>
      </div>

      {/* Alert title + preview + tactics */}
      <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 3 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
          <span
            className="sf-mono"
            style={{
              fontSize: 12.5,
              color: "var(--text)",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {alert.rule_name}
          </span>
          {tactics > 1 && (
            <span
              className="sf-mono"
              style={{
                fontSize: 9.5,
                color: "var(--accent)",
                border: "1px solid color-mix(in oklch, var(--accent) 30%, transparent)",
                padding: "1px 5px",
                flexShrink: 0,
                letterSpacing: "0.04em",
              }}
            >
              {tactics}× tactic
            </span>
          )}
        </div>
        <div
          style={{
            fontSize: 11.5,
            color: "var(--text-3)",
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          <span className="sf-mono" style={{ color: "var(--text-3)" }}>
            {alert.alert_id}
          </span>{" "}
          · {alert.message}
        </div>
      </div>

      {/* Entities */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "nowrap", minWidth: 0, overflow: "hidden" }}>
        {chips.slice(0, 2).map((c, i) => (
          <span
            key={i}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 5,
              padding: "2px 7px 2px 5px",
              border: "1px solid var(--line)",
              background: "var(--surface)",
              flexShrink: 0,
            }}
          >
            <span style={{ width: 12, height: 12, display: "inline-flex", alignItems: "center", justifyContent: "center" }}>
              <MiniEntityIcon kind={c.kind} />
            </span>
            <span className="sf-mono" style={{ fontSize: 11, color: "var(--text-2)" }}>
              {c.value}
            </span>
          </span>
        ))}
        {chips.length > 2 && (
          <span className="sf-mono" style={{ fontSize: 10.5, color: "var(--text-3)", flexShrink: 0 }}>
            +{chips.length - 2}
          </span>
        )}
      </div>

      {/* Events */}
      <span className="sf-mono sf-tnum" style={{ fontSize: 12, color: "var(--text-2)", textAlign: "right" }}>
        {alert.dedup_count.toLocaleString()}
      </span>

      {/* Status */}
      <StatusPill status={status} />

      {/* Owner */}
      <div data-testid="alert-owner">
        {owner ? (
          <span
            style={{
              width: 22,
              height: 22,
              border: "1px solid var(--line-2)",
              background: "var(--surface-2)",
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <span className="sf-mono" style={{ fontSize: 10, color: "var(--text-2)" }}>
              {owner}
            </span>
          </span>
        ) : (
          <span
            className="sf-mono"
            style={{ fontSize: 11, color: "var(--text-3)", border: "1px dashed var(--line)", padding: "2px 6px" }}
          >
            —
          </span>
        )}
      </div>

      {/* Updated */}
      <span className="sf-mono sf-tnum" style={{ fontSize: 11, color: "var(--text-3)", textAlign: "right" }}>
        {compactUpdated(alert.timestamp_ns)}
      </span>
    </div>
  );
}

export const AlertRow = memo(Row);
