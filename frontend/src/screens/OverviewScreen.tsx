import React from "react";
import { DashboardGrid } from "@/components/DashboardGrid/DashboardGrid";
import { AddWidgetMenu } from "@/components/DashboardGrid/AddWidgetMenu";
import { ResetLayoutButton } from "@/components/DashboardGrid/ResetLayoutButton";

/**
 * Overview screen — P0b interim wrapper.
 * Renders the existing DashboardGrid (with its Add/Reset controls) until the
 * full Overview redesign (S-320). S-320 will replace the body of this file
 * without touching the route registry or sidebar.
 *
 * The AddWidgetMenu and ResetLayoutButton were in the old App header; they now
 * live here as part of the overview screen chrome.
 */
export const OverviewScreen: React.FC = () => {
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "8px 16px",
          borderBottom: "1px solid var(--line)",
          background: "var(--bg)",
        }}
      >
        <AddWidgetMenu />
        <ResetLayoutButton />
      </div>
      <div style={{ flex: 1, overflow: "hidden" }}>
        <DashboardGrid />
      </div>
    </div>
  );
};
