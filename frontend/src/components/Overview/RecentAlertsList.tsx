import React from "react";
import { formatRelative } from "@/lib/relativeTime";
import { severityBucket } from "@/lib/severity";
import type { Alert } from "@/lib/types";

export interface RecentAlertsListProps {
  alerts: Alert[];
  /** Total alert count for the "view all N →" link. */
  totalCount?: number;
}

function getSeverityDot(severity: number): "crit" | "warn" {
  const bucket = severityBucket(severity);
  return bucket === "critical" || bucket === "high" ? "crit" : "warn";
}

const DOT_COLORS: Record<"crit" | "warn", string> = {
  crit: "var(--crit)",
  warn: "var(--warn)",
};

/**
 * Recent alerts list — shows top 5 alerts from the alert store.
 * Each row: severity dot + mono rule name + entity ref + score + relative time.
 */
export const RecentAlertsList: React.FC<RecentAlertsListProps> = ({
  alerts,
  totalCount,
}) => {
  const rows = alerts.slice(0, 5);

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "14px 24px",
          borderBottom: "1px solid var(--line)",
        }}
      >
        <div style={{ fontSize: 14, fontWeight: 600 }}>Recent alerts</div>
        {totalCount !== undefined && (
          <span
            className="sf-mono"
            style={{ fontSize: 11, color: "var(--text-2)", cursor: "pointer" }}
          >
            view all {totalCount} →
          </span>
        )}
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflow: "hidden" }}>
        {rows.length === 0 ? (
          <div
            data-testid="recent-alerts-empty"
            className="sf-mono"
            style={{
              padding: "24px",
              fontSize: 12,
              color: "var(--text-3)",
              textAlign: "center",
            }}
          >
            No alerts — pipeline is quiet.
          </div>
        ) : (
          rows.map((alert, i) => {
            const sevDot = getSeverityDot(alert.severity);
            return (
              <div
                key={alert.alert_id}
                data-testid={`alert-row-${alert.alert_id}`}
                style={{
                  display: "grid",
                  gridTemplateColumns: "24px 1fr auto auto",
                  alignItems: "center",
                  gap: 14,
                  padding: "11px 24px",
                  borderBottom: i < rows.length - 1 ? "1px solid var(--line)" : 0,
                  cursor: "pointer",
                }}
              >
                {/* Severity dot */}
                <span
                  data-testid={`severity-dot-${alert.alert_id}`}
                  data-severity={sevDot}
                  style={{
                    width: 8,
                    height: 8,
                    background: DOT_COLORS[sevDot],
                    flexShrink: 0,
                  }}
                />

                {/* Rule + entity */}
                <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
                  <div
                    className="sf-mono"
                    style={{
                      fontSize: 12.5,
                      color: "var(--text)",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {alert.rule_name}
                  </div>
                  {alert.entity_value && (
                    <div style={{ fontSize: 11.5, color: "var(--text-3)" }}>
                      entity:{" "}
                      <span style={{ color: "var(--accent)" }}>{alert.entity_value}</span>
                    </div>
                  )}
                </div>

                {/* Risk score */}
                <span
                  className="sf-mono sf-tnum"
                  style={{ fontSize: 11.5, color: "var(--text-2)" }}
                >
                  {alert.risk_score.toFixed(2)}
                </span>

                {/* Relative time */}
                <span
                  className="sf-mono sf-tnum"
                  style={{ fontSize: 11, color: "var(--text-3)", minWidth: 56, textAlign: "right" }}
                >
                  {formatRelative(alert.timestamp_ns)}
                </span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
