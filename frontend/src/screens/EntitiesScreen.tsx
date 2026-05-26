import React, { useEffect } from "react";
import { EntityDetail } from "@/components/EntityExplorer/EntityDetail";
import { useEntityStore } from "@/stores/entity";
import { hashHasEntity } from "@/lib/hash";

/**
 * Entities screen — P0b interim wrapper.
 * Renders the existing EntityDetail (which internally uses EntitySearch) until
 * the Entity graph redesign (S-322).
 * S-322 will replace the body of this file.
 *
 * Restores entity state from hash on mount/hash change — preserving the
 * behaviour from the old App.tsx that called restoreFromHash on hashchange.
 */
export const EntitiesScreen: React.FC = () => {
  const restoreFromHash = useEntityStore((s) => s.restoreFromHash);
  const clearSelection = useEntityStore((s) => s.clearSelection);

  useEffect(() => {
    const h = window.location.hash;
    if (hashHasEntity(h)) {
      void restoreFromHash(h);
    }

    const onHash = () => {
      const next = window.location.hash;
      if (hashHasEntity(next)) {
        void restoreFromHash(next);
      } else {
        clearSelection();
      }
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [restoreFromHash, clearSelection]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <EntityDetail />
    </div>
  );
};
