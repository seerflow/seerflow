/**
 * entityGraphAdapter — pure adapter between entity store data and
 * Cytoscape element definitions.
 *
 * All functions here are pure (no side effects, no DOM, no React) so they
 * can be thoroughly unit-tested without a Cytoscape instance.
 */

// --------------------------------------------------------------------------
// Input types (mirrors entity store shapes)
// --------------------------------------------------------------------------

export interface GraphEntity {
  entity_uuid: string;
  entity_type: string;
  entity_value: string;
  risk_score: number;
  event_count: number;
  alert_count: number;
}

export interface GraphRelation {
  source_uuid: string;
  target_uuid: string;
  relation_type: string;
  severity: number;
}

// --------------------------------------------------------------------------
// Output types (Cytoscape element shape)
// --------------------------------------------------------------------------

export type RiskColorKey = "crit" | "warn" | "accent" | "muted";

export interface CyNodeData {
  id: string;
  label: string;
  entityType: string;
  riskScore: number;
  eventCount: number;
  alertCount: number;
  colorKey: RiskColorKey;
  /** Normalized size (8–28px range for cy node width/height) */
  size: number;
}

export interface CyEdgeData {
  id: string;
  source: string;
  target: string;
  relationType: string;
  severity: number;
}

export interface CyNode {
  group: "nodes";
  data: CyNodeData;
}

export interface CyEdge {
  group: "edges";
  data: CyEdgeData;
}

export type CyElement = CyNode | CyEdge;

// --------------------------------------------------------------------------
// Risk helpers
// --------------------------------------------------------------------------

/** Map a risk score to a semantic color key. */
export function riskToColorKey(risk: number): RiskColorKey {
  if (risk >= 0.8) return "crit";
  if (risk >= 0.6) return "warn";
  if (risk >= 0.4) return "accent";
  return "muted";
}

type ColorTokens = {
  crit: string;
  warn: string;
  accent: string;
  text3: string;
};

/** Map a risk score to a concrete color string using resolved tokens. */
export function riskToColor(risk: number, tokens: ColorTokens): string {
  switch (riskToColorKey(risk)) {
    case "crit":   return tokens.crit;
    case "warn":   return tokens.warn;
    case "accent": return tokens.accent;
    default:       return tokens.text3;
  }
}

// --------------------------------------------------------------------------
// Node size scaling
// --------------------------------------------------------------------------

const NODE_SIZE_MIN = 8;
const NODE_SIZE_MAX = 28;
const LOG_SCALE_MAX = 10000;

function scaleNodeSize(eventCount: number): number {
  // log1p scale so low-count nodes are still visible
  const ratio = Math.log1p(Math.max(0, eventCount)) / Math.log1p(LOG_SCALE_MAX);
  return NODE_SIZE_MIN + (NODE_SIZE_MAX - NODE_SIZE_MIN) * Math.min(1, ratio);
}

// --------------------------------------------------------------------------
// Main adapter
// --------------------------------------------------------------------------

/**
 * Convert entity store data into Cytoscape element definitions.
 *
 * Duplicate edges (same source/target pair, regardless of relation_type)
 * are deduplicated — only the first occurrence is kept.
 *
 * @pure Does not mutate input arrays.
 */
export function storeRelationsToCyElements(
  entities: readonly GraphEntity[],
  relations: readonly GraphRelation[],
): { nodes: CyNode[]; edges: CyEdge[] } {
  const nodes: CyNode[] = entities.map((e) => ({
    group: "nodes" as const,
    data: {
      id: e.entity_uuid,
      label: e.entity_value,
      entityType: e.entity_type,
      riskScore: e.risk_score,
      eventCount: e.event_count,
      alertCount: e.alert_count,
      colorKey: riskToColorKey(e.risk_score),
      size: scaleNodeSize(e.event_count),
    },
  }));

  const seenEdges = new Set<string>();
  const edges: CyEdge[] = [];

  for (const r of relations) {
    const id = `${r.source_uuid}_${r.target_uuid}`;
    if (seenEdges.has(id)) continue;
    seenEdges.add(id);
    edges.push({
      group: "edges" as const,
      data: {
        id,
        source: r.source_uuid,
        target: r.target_uuid,
        relationType: r.relation_type,
        severity: r.severity,
      },
    });
  }

  return { nodes, edges };
}
