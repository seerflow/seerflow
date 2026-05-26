import React from "react";
import { AttackHeatmap } from "@/components/AttackHeatmap/AttackHeatmap";

/**
 * ATT&CK screen — P0b interim wrapper.
 * Renders the existing AttackHeatmap until the ATT&CK redesign (S-323).
 * S-323 will replace the body of this file.
 */
export const AttackScreen: React.FC = () => {
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <AttackHeatmap />
    </div>
  );
};
