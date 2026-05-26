import React from "react";
import { EntityDetail } from "@/components/EntityExplorer/EntityDetail";

/**
 * Entities screen — P0b interim wrapper.
 * Renders the existing EntityDetail (which internally uses EntitySearch) until
 * the Entity graph redesign (S-322).
 * S-322 will replace the body of this file.
 */
export const EntitiesScreen: React.FC = () => {
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <EntityDetail />
    </div>
  );
};
