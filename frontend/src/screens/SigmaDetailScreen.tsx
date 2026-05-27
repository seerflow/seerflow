import React from "react";

/**
 * Sigma rule detail screen — S-324 seam.
 * Currently the AppShell routes both #/sigma and #/sigma/:id to SigmaScreen
 * (which handles selection internally via the split-panel layout).
 * S-324: this file exists as a future seam for deep-linked detail routes.
 */
export const SigmaDetailScreen: React.FC = () => {
  return (
    <div
      data-testid="sigma-detail-screen"
      style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}
    />
  );
};
