/**
 * EntitiesScreen — S-322 entity graph redesign.
 *
 * Replaces the P0b interim EntityDetail wrapper with a full three-column
 * entity graph screen: filter rail | EntityGraphCanvas | inspector.
 *
 * Wires the entity store to the EntityExplorerGraph component:
 * - nodes  = focal entity + related entities (mapped to GraphEntity)
 * - edges  = related entities mapped to GraphRelation pairs
 * - selected node → store.selectEntity + navigateToEntity
 * - double-click node → navigateToEntity
 * - hash restore on mount/hashchange (preserves pre-S-322 route behaviour)
 */

import React, { useCallback, useEffect, useMemo } from "react";
import { EntityExplorerGraph } from "@/components/EntityExplorer/EntityExplorerGraph";
import { useEntityStore } from "@/stores/entity";
import { hashHasEntity, navigateToEntity } from "@/lib/hash";
import type { GraphEntity, GraphRelation } from "@/viz/entityGraphAdapter";

// ── Helpers ───────────────────────────────────────────────────────────────

/**
 * Build graph nodes from focal entity + related neighbours.
 * EntityRelation doesn't carry risk_score / event_count / alert_count — use
 * defaults (0.0 / 0 / 0) for related nodes. The focal entity uses the values
 * available in the store's searchResults / recent, if found.
 */
function buildGraphNodes(
  selectedUuid: string | null,
  selectedType: string | null,
  selectedValue: string | null,
  related: import("@/lib/types").EntityRelation[],
  searchResults: import("@/lib/types").EntitySearchResult[],
  recent: import("@/lib/types").EntitySearchResult[],
): GraphEntity[] {
  const nodes: GraphEntity[] = [];

  if (selectedUuid) {
    // Try to find richer data from search / recent cache
    const cached =
      searchResults.find((r) => r.entity_uuid === selectedUuid) ??
      recent.find((r) => r.entity_uuid === selectedUuid);

    nodes.push({
      entity_uuid: selectedUuid,
      entity_type: selectedType ?? cached?.entity_type ?? "host",
      entity_value: selectedValue ?? cached?.entity_value ?? selectedUuid.slice(0, 8),
      risk_score: 0.0,
      event_count: 0,
      alert_count: 0,
    });
  }

  // Add related as separate nodes (dedup by uuid)
  const seen = new Set<string>(selectedUuid ? [selectedUuid] : []);
  for (const r of related) {
    if (seen.has(r.entity_uuid)) continue;
    seen.add(r.entity_uuid);
    nodes.push({
      entity_uuid: r.entity_uuid,
      entity_type: r.entity_type,
      entity_value: r.entity_value,
      risk_score: 0.0,
      event_count: 0,
      alert_count: 0,
    });
  }

  return nodes;
}

/**
 * Build graph edges: one directed edge from focal to each related node.
 */
function buildGraphEdges(
  selectedUuid: string | null,
  related: import("@/lib/types").EntityRelation[],
): GraphRelation[] {
  if (!selectedUuid) return [];
  return related.map((r) => ({
    source_uuid: selectedUuid,
    target_uuid: r.entity_uuid,
    relation_type: r.relation_type,
    severity: 0.5,
  }));
}

// ── Screen ────────────────────────────────────────────────────────────────

export const EntitiesScreen: React.FC = () => {
  const restoreFromHash = useEntityStore((s) => s.restoreFromHash);
  const clearSelection  = useEntityStore((s) => s.clearSelection);
  const selectEntity    = useEntityStore((s) => s.selectEntity);

  const selectedUuid  = useEntityStore((s) => s.selectedEntityUuid);
  const selectedType  = useEntityStore((s) => s.selectedEntityType);
  const selectedValue = useEntityStore((s) => s.selectedEntityValue);
  const related       = useEntityStore((s) => s.related);
  const events        = useEntityStore((s) => s.events);
  const searchResults = useEntityStore((s) => s.searchResults);
  const recent        = useEntityStore((s) => s.recent);

  // ── Hash routing (preserves pre-S-322 behaviour) ──────────────────────
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

  // ── Derived graph data ────────────────────────────────────────────────
  const graphNodes = useMemo(
    () =>
      buildGraphNodes(
        selectedUuid,
        selectedType,
        selectedValue,
        related,
        searchResults,
        recent,
      ),
    [selectedUuid, selectedType, selectedValue, related, searchResults, recent],
  );

  const graphEdges = useMemo(
    () => buildGraphEdges(selectedUuid, related),
    [selectedUuid, related],
  );

  // ── Handlers ─────────────────────────────────────────────────────────
  const handleNodeSelect = useCallback(
    (id: string | null) => {
      if (!id) {
        clearSelection();
        return;
      }
      void selectEntity(id);
    },
    [selectEntity, clearSelection],
  );

  const handleNodeDblClick = useCallback((id: string) => {
    navigateToEntity(id);
  }, []);

  return (
    <div
      data-testid="entities-screen"
      style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}
    >
      <EntityExplorerGraph
        nodes={graphNodes}
        edges={graphEdges}
        selectedUuid={selectedUuid}
        onNodeSelect={handleNodeSelect}
        onNodeDblClick={handleNodeDblClick}
        events={events}
        related={related}
        className="flex-1 min-h-0"
      />
    </div>
  );
};
