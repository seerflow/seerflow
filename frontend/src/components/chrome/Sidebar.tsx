import React from "react";
import { SeerMark } from "@/components/brand/SeerMark";
import { ROUTE_REGISTRY, type RouteName, type NavGroup } from "@/lib/routes";
import { useAlertStore } from "@/stores/alerts";
import { useStatusStore } from "@/stores/status";

const APP_VERSION = "0.5.0";

export interface SidebarProps {
  activeRoute: RouteName;
  onNavigate: (route: RouteName) => void;
}

const NAV_GROUPS: NavGroup[] = ["Monitor", "Investigate", "Configure"];

/**
 * Dashboard sidebar.
 * 212px wide; persistent. Shows brand header, 3 nav groups, status footer.
 * Active item: var(--surface) bg + 2px left var(--accent) border.
 */
export const Sidebar: React.FC<SidebarProps> = ({ activeRoute, onNavigate }) => {
  const alertCount = useAlertStore((s) => s.alerts.length);
  const { pipelineOnline, uptimeLabel, evPerSec } = useStatusStore();

  return (
    <div
      style={{
        gridArea: "sidebar",
        borderRight: "1px solid var(--line)",
        background: "var(--bg)",
        display: "flex",
        flexDirection: "column",
        width: 212,
        boxSizing: "border-box",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "15px 18px",
          borderBottom: "1px solid var(--line)",
          height: 52,
          boxSizing: "border-box",
        }}
      >
        <SeerMark size={20} variant="color" />
        <span
          style={{
            fontSize: 14.5,
            fontWeight: 600,
            letterSpacing: "-0.02em",
            color: "var(--text)",
          }}
        >
          seerflow
        </span>
        <span style={{ flex: 1 }} />
        <span
          data-testid="version-badge"
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            color: "var(--text-3)",
            border: "1px solid var(--line)",
            padding: "1px 4px",
          }}
        >
          {APP_VERSION}
        </span>
      </div>

      {/* Nav groups */}
      <div style={{ flex: 1, padding: "14px 0", overflow: "auto" }}>
        {NAV_GROUPS.map((group) => {
          const items = ROUTE_REGISTRY.filter((r) => r.group === group);
          return (
            <div key={group} style={{ marginBottom: 14 }}>
              <div
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 10,
                  color: "var(--text-3)",
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  padding: "6px 18px",
                }}
              >
                {group}
              </div>
              {items.map(({ route, label, iconPath }) => {
                const isActive = activeRoute === route;
                return (
                  <div
                    key={route}
                    data-testid={`nav-item-${route}`}
                    data-active={isActive ? "true" : undefined}
                    role="button"
                    tabIndex={0}
                    onClick={() => onNavigate(route)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") onNavigate(route);
                    }}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                      padding: "7px 18px 7px 16px",
                      fontSize: 13,
                      color: isActive ? "var(--text)" : "var(--text-2)",
                      background: isActive ? "var(--surface)" : "transparent",
                      borderLeft: isActive
                        ? "2px solid var(--accent)"
                        : "2px solid transparent",
                      cursor: "pointer",
                      fontWeight: isActive ? 500 : 400,
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
                      style={{ opacity: isActive ? 1 : 0.72, flexShrink: 0 }}
                    >
                      <path d={iconPath} />
                    </svg>
                    <span>{label}</span>
                    {route === "alerts" && (
                      <span style={{ marginLeft: "auto" }}>
                        <span
                          data-testid="alerts-count-badge"
                          style={{
                            fontFamily: "var(--font-mono)",
                            fontSize: 10,
                            color: "var(--crit)",
                            border:
                              "1px solid color-mix(in oklch, var(--crit) 35%, transparent)",
                            background:
                              "color-mix(in oklch, var(--crit) 12%, transparent)",
                            padding: "1px 5px",
                          }}
                        >
                          {alertCount}
                        </span>
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>

      {/* Footer */}
      <div
        style={{
          padding: "14px 18px",
          borderTop: "1px solid var(--line)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: 3,
              background: pipelineOnline ? "var(--accent)" : "var(--text-3)",
              flexShrink: 0,
            }}
          />
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              color: "var(--text-2)",
            }}
          >
            {pipelineOnline ? "pipeline online" : "pipeline offline"}
          </span>
        </div>
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10.5,
            color: "var(--text-3)",
            marginTop: 4,
          }}
        >
          {pipelineOnline
            ? `uptime ${uptimeLabel} · ${evPerSec.toLocaleString()} ev/s`
            : "—"}
        </div>
      </div>
    </div>
  );
};
