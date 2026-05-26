import React from "react";
import { SigmaRulesPage } from "@/components/SigmaRules/SigmaRulesPage";

/**
 * Sigma rules screen — P0b interim wrapper.
 * Renders the existing SigmaRulesPage until the Sigma rules redesign (S-324).
 * S-324 will replace the body of this file.
 *
 * The route #/sigma/:id sub-route is handled here by passing the sigma rule id
 * through to SigmaRulesPage if needed. Currently SigmaRulesPage manages its
 * own selection state internally.
 */
export const SigmaScreen: React.FC = () => {
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <SigmaRulesPage />
    </div>
  );
};
