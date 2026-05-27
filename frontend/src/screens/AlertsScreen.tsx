import React from "react";
import { AlertFeed } from "@/components/AlertFeed/AlertFeed";

/**
 * Alerts list screen — S-336 SOC-console rebuild.
 *
 * Renders the live AlertFeed full-bleed (flush, no padding wrapper) like the
 * other redesigned screens. AlertFeed owns the WS subscription, REST backfill,
 * status tabs, filter chips, volume strip, the 8-column triage table, and the
 * client-side pagination footer.
 *
 * Row clicks navigate to the full detail page (#/alerts/:id, AlertDetailScreen)
 * — there is no inline detail panel in the feed anymore. The TP/FP feedback
 * capability that used to live in the feed's inline panel is being relocated to
 * the detail page in a follow-up story.
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
      }}
    >
      <AlertFeed />
    </div>
  );
};
