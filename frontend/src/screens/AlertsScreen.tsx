import React from "react";
import { AlertFeed } from "@/components/AlertFeed/AlertFeed";

/**
 * Alerts list screen — S-321 redesign.
 *
 * Renders the live AlertFeed full-screen with its built-in inline detail
 * panel. AlertFeed manages WS subscription, backfill, filtering, and the
 * inline AlertDetailPanel (with feedback buttons) on row click.
 *
 * Direct navigation to a specific alert (#/alerts/:id) is handled by
 * AlertDetailScreen, which the shell routes to when an id is present in the
 * hash. This screen intentionally keeps row clicks within the #/alerts view
 * so the inline panel (feedback, MITRE, contributing events) remains
 * accessible without a full-page navigation.
 */
export const AlertsScreen: React.FC = () => {
  return (
    <div
      data-testid="alerts-screen"
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        overflow: "hidden",
        padding: "12px",
      }}
    >
      <AlertFeed />
    </div>
  );
};
