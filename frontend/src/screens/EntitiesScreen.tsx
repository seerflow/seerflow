/**
 * EntitiesScreen — S-322 entity graph redesign.
 *
 * Replaces the P0b interim EntityDetail wrapper with a full three-column
 * entity graph screen: filter rail | EntityGraphCanvas | inspector.
 *
 * Wires the entity store to the EntityExplorerGraph component:
 * - nodes  = focal entity + related entities (mapped to GraphEntity)
 * - edges  = related entities mapped to GraphRelation pairs
 * - selected node → store.selectEntity (lifts selection into the inspector)
 * - double-click node → drill into the node's depth-1 neighborhood (S-326)
 * - hash restore on mount/hashchange (preserves pre-S-322 route behaviour)
 */

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { EntityExplorerGraph } from "@/components/EntityExplorer/EntityExplorerGraph";
import { useEntityStore } from "@/stores/entity";
import { hashHasEntity } from "@/lib/hash";
import { selectFocalEntityStats, type FocalEntityStats } from "@/lib/liveStats";
import type { GraphEntity, GraphRelation } from "@/viz/entityGraphAdapter";

// ── Helpers ───────────────────────────────────────────────────────────────

/**
 * Build graph nodes from focal entity + related neighbours.
 * EntityRelation doesn't carry risk_score / event_count / alert_count — use
 * defaults (0.0 / 0 / 0) for related nodes. The focal entity's stats are
 * computed from the store's timeline data (S-328) and passed in via
 * `focalStats`; its label uses search / recent cache when available.
 */
function buildGraphNodes(
  selectedUuid: string | null,
  selectedType: string | null,
  selectedValue: string | null,
  related: import("@/lib/types").EntityRelation[],
  searchResults: import("@/lib/types").EntitySearchResult[],
  recent: import("@/lib/types").EntitySearchResult[],
  focalStats: FocalEntityStats,
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
      risk_score: focalStats.risk,
      event_count: focalStats.eventCount,
      alert_count: focalStats.alertCount,
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
  const total         = useEntityStore((s) => s.total);
  const riskHistory   = useEntityStore((s) => s.riskHistory);
  const searchResults = useEntityStore((s) => s.searchResults);
  const recent        = useEntityStore((s) => s.recent);

  // ── Drill state (ephemeral view state, not the store) ──────────────────
  const [drillUuid, setDrillUuid] = useState<string | null>(null);

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
  // Focal-entity inspector stats computed from the store timeline (S-328 AC3).
  // `total` / `riskHistory` may be absent on the very first render or under a
  // lean test mock — guard with safe defaults so demo mode is unaffected.
  const focalStats = useMemo(
    () => selectFocalEntityStats(events, total ?? 0, riskHistory ?? []),
    [events, total, riskHistory],
  );

  const graphNodes = useMemo(
    () =>
      buildGraphNodes(
        selectedUuid,
        selectedType,
        selectedValue,
        related,
        searchResults,
        recent,
        focalStats,
      ),
    [selectedUuid, selectedType, selectedValue, related, searchResults, recent, focalStats],
  );

  const graphEdges = useMemo(
    () => buildGraphEdges(selectedUuid, related),
    [selectedUuid, related],
  );

  // ── Drill: filter to drilled node + depth-1 neighbours (S-326) ─────────
  const displayNodes = useMemo(() => {
    if (!drillUuid) return graphNodes;
    const keep = new Set<string>([drillUuid]);
    for (const e of graphEdges) {
      if (e.source_uuid === drillUuid) keep.add(e.target_uuid);
      if (e.target_uuid === drillUuid) keep.add(e.source_uuid);
    }
    return graphNodes.filter((n) => keep.has(n.entity_uuid));
  }, [drillUuid, graphNodes, graphEdges]);

  const displayEdges = useMemo(() => {
    if (!drillUuid) return graphEdges;
    const ids = new Set(displayNodes.map((n) => n.entity_uuid));
    return graphEdges.filter(
      (e) => ids.has(e.source_uuid) && ids.has(e.target_uuid),
    );
  }, [drillUuid, graphEdges, displayNodes]);

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
    setDrillUuid(id);
  }, []);

  const handleClearDrill = useCallback(() => setDrillUuid(null), []);

  const setRange = useEntityStore((s) => s.setRange);
  const handleTimeWindowChange = useCallback(
    (window: string) => {
      // Map graph time-window chip labels to entity store TimelineRange values
      const MAP: Record<string, import("@/lib/types").TimelineRange> = {
        "15m": "1h",   // closest store range is 1h (no 15m store range)
        "1h":  "1h",
        "24h": "24h",
        "7d":  "7d",
      };
      const range = MAP[window];
      if (range) void setRange(range);
    },
    [setRange],
  );

  return (
    <div
      data-testid="entities-screen"
      style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}
    >
      <EntityExplorerGraph
        nodes={displayNodes}
        edges={displayEdges}
        selectedUuid={selectedUuid}
        onNodeSelect={handleNodeSelect}
        onNodeDblClick={handleNodeDblClick}
        onTimeWindowChange={handleTimeWindowChange}
        drillActive={drillUuid !== null}
        onClearDrill={handleClearDrill}
        events={events}
        related={related}
        className="flex-1 min-h-0"
      />
    </div>
  );
};
