import React from "react";
import { AttackHeatmap } from "@/components/AttackHeatmap/AttackHeatmap";

/**
 * ATT&CK screen — S-323 redesign.
 * Thin shell providing the outer flex container; all layout lives in AttackHeatmap.
 */
export const AttackScreen: React.FC = () => {
  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden">
      <AttackHeatmap />
    </div>
  );
};
