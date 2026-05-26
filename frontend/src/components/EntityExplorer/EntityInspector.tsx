/**
 * EntityInspector — right-rail inspector for the entity graph screen (S-322).
 *
 * Shows: entity header, 2×2 stat grid, linked alerts, recent events.
 * Driven by a selectedUuid + the nodes/events/related arrays from the store.
 */

import React from "react";
import {
  Stat,
  SideBlock,
  EntityGlyph,
  RiskBar,
} from "@/components/ui/primitives";
import type { GraphEntity } from "@/viz/entityGraphAdapter";
import type { EntityEvent, EntityRelation } from "@/lib/types";
import type { EntityType } from "@/components/ui/primitives";

// ── Severity helpers ──────────────────────────────────────────────────────

const SEV_COLORS: Record<number, string> = {
  5: "var(--crit)",
  6: "var(--crit)",
  4: "var(--warn)",
  3: "var(--warn)",
  2: "var(--text-3)",
  1: "var(--text-3)",
  0: "var(--text-3)",
};

function sevColor(id: number): string {
  return SEV_COLORS[id] ?? "var(--text-3)";
}

function formatTs(ns: bigint): string {
  const ms = Number(ns / 1_000_000n);
  const d = new Date(ms);
  return d.toISOString().slice(11, 19);
}

// ── KNOWN_TYPES ───────────────────────────────────────────────────────────

const KNOWN_ENTITY_TYPES = new Set<string>(["user", "host", "ip", "service", "process"]);

function toGlyphType(t: string): EntityType {
  return KNOWN_ENTITY_TYPES.has(t) ? (t as EntityType) : "host";
}

// ── Props ─────────────────────────────────────────────────────────────────

export interface EntityInspectorProps {
  selectedUuid: string | null;
  nodes: GraphEntity[];
  events: EntityEvent[];
  related: EntityRelation[];
  className?: string;
}

// ── Component ─────────────────────────────────────────────────────────────

export const EntityInspector: React.FC<EntityInspectorProps> = ({
  selectedUuid,
  nodes,
  events,
  related,
  className,
}) => {
  if (!selectedUuid) {
    return (
      <div
        data-testid="inspector-empty"
        className={`flex flex-col items-center justify-center h-full text-text-3 sf-mono text-[11px] ${className ?? ""}`}
      >
        select a node
      </div>
    );
  }

  const node = nodes.find((n) => n.entity_uuid === selectedUuid);
  const neighborCount = related.length;

  // Recent events — up to 5
  const recentEvents = events.slice(0, 5);

  // Linked alerts — events with severity_id >= 3
  const linkedAlertEvents = events.filter((e) => e.severity_id >= 3).slice(0, 4);

  return (
    <div className={`flex flex-col overflow-auto ${className ?? ""}`}>
      {/* ── Selected section ── */}
      <SideBlock title="Selected">
        {node ? (
          <>
            {/* Entity header */}
            <div
              data-testid="inspector-entity-header"
              className="flex items-center gap-3 mb-3"
            >
              <EntityGlyph
                type={toGlyphType(node.entity_type)}
                size={36}
                className="border-[color:var(--crit)] flex-shrink-0"
              />
              <div className="min-w-0">
                <div className="sf-mono text-[14px] text-text truncate">
                  {node.entity_value}
                </div>
                <div className="sf-mono text-[10px] text-text-3 uppercase tracking-[0.06em]">
                  {node.entity_type.toUpperCase()} · {node.entity_uuid.slice(-12)}
                </div>
              </div>
            </div>
            {/* Risk bar */}
            <RiskBar value={node.risk_score} className="mb-3" />
            {/* 2×2 stat grid */}
            <div className="grid grid-cols-2 gap-px bg-line border border-line">
              {[
                { label: "risk",      value: node.risk_score.toFixed(2) },
                { label: "events",    value: node.event_count.toLocaleString() },
                { label: "neighbors", value: String(neighborCount) },
                { label: "alerts",    value: String(node.alert_count) },
              ].map(({ label, value }) => (
                <div key={label} className="px-3 py-2.5 bg-surface">
                  <Stat label={label} value={value} />
                </div>
              ))}
            </div>
          </>
        ) : (
          <div className="sf-mono text-[11px] text-text-3">
            {selectedUuid.slice(0, 8)}…
          </div>
        )}
      </SideBlock>

      {/* ── Linked alerts section ── */}
      <SideBlock title="Linked alerts">
        <div data-testid="inspector-linked-alerts">
          {linkedAlertEvents.length === 0 ? (
            <div className="sf-mono text-[11px] text-text-3">no alerts</div>
          ) : (
            linkedAlertEvents.map((ev) => (
              <div
                key={ev.event_id}
                className="grid gap-2.5 items-center py-2 border-b border-dashed border-line"
                style={{ gridTemplateColumns: "8px 1fr auto" }}
              >
                <span
                  className="flex-shrink-0"
                  style={{
                    width: 6,
                    height: 6,
                    background: sevColor(ev.severity_id),
                    display: "inline-block",
                  }}
                />
                <div>
                  <div className="sf-mono text-[11px] text-accent truncate">
                    {ev.event_id.slice(0, 12)}
                  </div>
                  <div className="text-[12px] text-text-2 truncate">{ev.message}</div>
                </div>
                <span className="text-[13px] text-text-3">→</span>
              </div>
            ))
          )}
        </div>
      </SideBlock>

      {/* ── Recent events section ── */}
      <SideBlock title="Recent events">
        <div
          data-testid="inspector-recent-events"
          className="sf-mono text-[11px] text-text-2"
          style={{ lineHeight: 1.7 }}
        >
          {recentEvents.length === 0 ? (
            <div className="text-text-3">no events</div>
          ) : (
            recentEvents.map((ev) => (
              <div key={ev.event_id} className="flex gap-2 min-w-0">
                <span className="text-text-3 flex-shrink-0">
                  {formatTs(ev.timestamp_ns)}
                </span>
                <span
                  className="truncate"
                  style={{ color: sevColor(ev.severity_id) }}
                >
                  {ev.message}
                </span>
              </div>
            ))
          )}
        </div>
      </SideBlock>
    </div>
  );
};
