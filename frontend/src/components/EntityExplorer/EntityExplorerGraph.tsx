/**
 * EntityExplorerGraph — full entity graph screen body (S-322).
 *
 * Layout: 260px / 1fr / 280px
 * Left rail: Filter (types checklist, min-risk slider, time chips, layout chips) + Legend
 * Center: EntityGraphCanvas with zoom/fit toolbar + node/edge/depth counter
 * Right: EntityInspector (selected entity stats, linked alerts, recent events)
 */

import React, { useMemo, useState } from "react";
import {
  SideBlock,
  FilterChip,
  FilterRow,
  Legend,
} from "@/components/ui/primitives";
import type { LegendItemData } from "@/components/ui/primitives";
import { EntityGraphCanvas } from "@/viz/EntityGraphCanvas";
import type { GraphLayout } from "@/viz/EntityGraphCanvas";
import type { GraphEntity, GraphRelation } from "@/viz/entityGraphAdapter";
import type { EntityEvent, EntityRelation } from "@/lib/types";
import { EntityInspector } from "./EntityInspector";

// ── Constants ─────────────────────────────────────────────────────────────

const ENTITY_TYPES = ["user", "host", "ip", "service", "process"] as const;
type KnownType = (typeof ENTITY_TYPES)[number];

const LAYOUTS: GraphLayout[] = ["Force", "Radial", "Hierarchy"];
const TIME_WINDOWS = ["15m", "1h", "24h", "7d"] as const;
type TimeWindow = (typeof TIME_WINDOWS)[number];

const LEGEND_ITEMS: LegendItemData[] = [
  { color: "var(--crit)",   label: "risk ≥ 0.8" },
  { color: "var(--warn)",   label: "risk 0.6–0.8" },
  { color: "var(--accent)", label: "risk 0.4–0.6" },
  { color: "var(--text-3)", label: "risk < 0.4" },
];

// ── Props ─────────────────────────────────────────────────────────────────

export interface EntityExplorerGraphProps {
  nodes: GraphEntity[];
  edges: GraphRelation[];
  selectedUuid: string | null;
  onNodeSelect: (id: string | null) => void;
  onNodeDblClick: (id: string) => void;
  /** Called when the user changes the time-window chip — parent should call store.setRange */
  onTimeWindowChange?: (window: string) => void;
  events: EntityEvent[];
  related: EntityRelation[];
  className?: string;
}

// ── Component ─────────────────────────────────────────────────────────────

export const EntityExplorerGraph: React.FC<EntityExplorerGraphProps> = ({
  nodes,
  edges,
  selectedUuid,
  onNodeSelect,
  // onNodeDblClick wiring: EntityGraphCanvas (S-319) has no onNodeDblClick prop.
  // Double-click neighborhood navigation is deferred pending a canvas prop addition
  // in a follow-up story (see deferred_issues in S-322 PR). The prop is kept in the
  // interface so callers can wire it when the canvas gains support.
  onNodeDblClick: _onNodeDblClick, // eslint-disable-line @typescript-eslint/no-unused-vars
  onTimeWindowChange,
  events,
  related,
  className,
}) => {
  // ── Filter state ──
  const [activeTypes, setActiveTypes] = useState<Set<KnownType>>(
    new Set(ENTITY_TYPES),
  );
  const [minRisk, setMinRisk] = useState<number>(0);
  const [timeWindow, setTimeWindow] = useState<TimeWindow>("24h");
  const [layout, setLayout] = useState<GraphLayout>("Force");

  // ── Derived filtered nodes ──
  const visibleNodes = useMemo(
    () =>
      nodes.filter(
        (n) =>
          (activeTypes as Set<string>).has(n.entity_type) &&
          n.risk_score >= minRisk,
      ),
    [nodes, activeTypes, minRisk],
  );

  // Keep only edges whose both endpoints are visible
  const visibleNodeIds = useMemo(
    () => new Set(visibleNodes.map((n) => n.entity_uuid)),
    [visibleNodes],
  );
  const visibleEdges = useMemo(
    () =>
      edges.filter(
        (e) =>
          visibleNodeIds.has(e.source_uuid) &&
          visibleNodeIds.has(e.target_uuid),
      ),
    [edges, visibleNodeIds],
  );

  // Type counts
  const typeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const n of nodes) {
      counts[n.entity_type] = (counts[n.entity_type] ?? 0) + 1;
    }
    return counts;
  }, [nodes]);

  // ── Handlers ──
  function toggleType(t: KnownType) {
    setActiveTypes((prev) => {
      const next = new Set(prev);
      if (next.has(t)) {
        next.delete(t);
      } else {
        next.add(t);
      }
      return next;
    });
  }

  return (
    <div
      data-testid="entity-explorer-graph"
      className={`grid h-full overflow-hidden ${className ?? ""}`}
      style={{ gridTemplateColumns: "260px 1fr 280px" }}
    >
      {/* ── Left rail ── */}
      <div
        data-testid="graph-left-rail"
        className="border-r border-line overflow-auto"
        style={{ padding: "18px" }}
      >
        <SideBlock title="Filter">
          {/* Types checklist */}
          <div className="mb-4">
            <div className="sf-mono text-[10px] text-text-3 uppercase tracking-[0.1em] mb-2">
              Types
            </div>
            <div className="flex flex-col gap-1">
              {ENTITY_TYPES.map((t) => {
                const active = activeTypes.has(t);
                return (
                  <button
                    key={t}
                    role="checkbox"
                    aria-checked={active}
                    data-testid={`type-filter-${t}`}
                    onClick={() => toggleType(t)}
                    className="flex items-center gap-2 py-1 text-left cursor-pointer hover:text-text transition-colors"
                  >
                    <span
                      className="flex-shrink-0 flex items-center justify-center border border-line-2"
                      style={{
                        width: 12,
                        height: 12,
                        background: active ? "var(--accent)" : "transparent",
                      }}
                    >
                      {active && (
                        <svg
                          width="8"
                          height="8"
                          viewBox="0 0 8 8"
                          fill="none"
                          stroke="var(--accent-ink, var(--bg))"
                          strokeWidth="1.6"
                        >
                          <path d="M1.5 4l2 2 3-4" />
                        </svg>
                      )}
                    </span>
                    <span className="text-[12.5px] text-text flex-1 capitalize">{t}</span>
                    <span className="sf-mono sf-tnum text-[11px] text-text-3">
                      {typeCounts[t] ?? 0}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Min-risk slider */}
          <div className="mb-4">
            <div className="sf-mono text-[10px] text-text-3 uppercase tracking-[0.1em] mb-2">
              Min risk
            </div>
            <div className="flex items-center gap-2">
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={minRisk}
                aria-label="Min risk"
                onChange={(e) => setMinRisk(Number(e.target.value))}
                className="flex-1"
                style={{ accentColor: "var(--accent)" }}
              />
              <span className="sf-mono sf-tnum text-[11px] text-text-2" style={{ minWidth: 28 }}>
                {minRisk.toFixed(2)}
              </span>
            </div>
          </div>

          {/* Time window chips */}
          <div className="mb-4">
            <div className="sf-mono text-[10px] text-text-3 uppercase tracking-[0.1em] mb-2">
              Time window
            </div>
            <FilterRow>
              {TIME_WINDOWS.map((w) => (
                <FilterChip
                  key={w}
                  label={w}
                  active={timeWindow === w}
                  onClick={() => {
                    setTimeWindow(w);
                    onTimeWindowChange?.(w);
                  }}
                />
              ))}
            </FilterRow>
          </div>

          {/* Layout chips */}
          <div className="mb-4">
            <div className="sf-mono text-[10px] text-text-3 uppercase tracking-[0.1em] mb-2">
              Layout
            </div>
            <FilterRow>
              {LAYOUTS.map((l) => (
                <FilterChip
                  key={l}
                  label={l}
                  active={layout === l}
                  onClick={() => setLayout(l)}
                />
              ))}
            </FilterRow>
          </div>
        </SideBlock>

        {/* Legend */}
        <SideBlock title="Legend">
          <div
            data-testid="graph-legend"
            className="flex flex-col gap-2"
          >
            <Legend items={LEGEND_ITEMS} className="flex-col items-start gap-2" />
          </div>
        </SideBlock>
      </div>

      {/* ── Center canvas ── */}
      <div
        data-testid="graph-center"
        className="relative overflow-hidden"
        style={{ background: "var(--bg)" }}
      >
        {/* Dot-grid background */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            backgroundImage:
              "radial-gradient(circle, var(--line) 1px, transparent 1px)",
            backgroundSize: "24px 24px",
            opacity: 0.4,
          }}
        />

        {/* Canvas — absolute fill so Cytoscape has a concrete pixel size */}
        <div className="absolute inset-0">
          <EntityGraphCanvas
            nodes={visibleNodes}
            edges={visibleEdges}
            layout={layout}
            fitOnChange
            onNodeSelect={onNodeSelect}
            className="w-full h-full"
          />
        </div>

        {/* Zoom/fit toolbar (top-left overlay) */}
        <div className="absolute top-3.5 left-3.5 flex gap-1.5 z-10">
          {(["fit", "+", "−", "⤢"] as const).map((label) => (
            <button
              key={label}
              aria-label={label === "fit" ? "Fit graph" : label === "+" ? "Zoom in" : label === "−" ? "Zoom out" : "Fullscreen"}
              className="w-7 h-7 bg-surface border border-line text-text-2 text-[12px] cursor-pointer hover:border-line-2 hover:text-text transition-colors flex items-center justify-center"
            >
              {label}
            </button>
          ))}
        </div>

        {/* Node/edge/depth counter (bottom-left overlay) */}
        <div
          data-testid="graph-counter"
          className="absolute bottom-3.5 left-3.5 px-2.5 py-1.5 bg-surface border border-line z-10"
        >
          <span className="sf-mono sf-tnum text-[11px] text-text-2">
            {visibleNodes.length} nodes · {visibleEdges.length} edges · depth 1
          </span>
        </div>
      </div>

      {/* ── Right inspector ── */}
      <div
        data-testid="graph-right-inspector"
        className="border-l border-line overflow-auto"
      >
        {/* Pass all nodes (not just visibleNodes) so the inspector keeps showing
            the selected entity's data even if it gets filtered out by type/risk */}
        <EntityInspector
          selectedUuid={selectedUuid}
          nodes={nodes}
          events={events}
          related={related}
        />
      </div>
    </div>
  );
};
