import { describe, it, expect } from "vitest";
import {
  storeRelationsToCyElements,
  riskToColor,
  riskToColorKey,
  type CyNode,
  type CyEdge,
  type GraphEntity,
  type GraphRelation,
} from "./entityGraphAdapter";

// --------------------------------------------------------------------------
// Test data helpers
// --------------------------------------------------------------------------
const makeEntity = (overrides: Partial<GraphEntity> = {}): GraphEntity => ({
  entity_uuid: "uuid-001",
  entity_type: "host",
  entity_value: "web-04",
  risk_score: 0.5,
  event_count: 100,
  alert_count: 1,
  ...overrides,
});

const makeRelation = (overrides: Partial<GraphRelation> = {}): GraphRelation => ({
  source_uuid: "uuid-001",
  target_uuid: "uuid-002",
  relation_type: "logged_into",
  severity: 0.5,
  ...overrides,
});

// --------------------------------------------------------------------------
describe("riskToColorKey", () => {
  it("returns 'crit' for risk >= 0.8", () => {
    expect(riskToColorKey(0.8)).toBe("crit");
    expect(riskToColorKey(0.94)).toBe("crit");
    expect(riskToColorKey(1.0)).toBe("crit");
  });

  it("returns 'warn' for risk 0.6–0.8 (exclusive 0.8)", () => {
    expect(riskToColorKey(0.6)).toBe("warn");
    expect(riskToColorKey(0.79)).toBe("warn");
    expect(riskToColorKey(0.65)).toBe("warn");
  });

  it("returns 'accent' for risk 0.4–0.6 (exclusive 0.6)", () => {
    expect(riskToColorKey(0.4)).toBe("accent");
    expect(riskToColorKey(0.5)).toBe("accent");
    expect(riskToColorKey(0.59)).toBe("accent");
  });

  it("returns 'muted' for risk < 0.4", () => {
    expect(riskToColorKey(0.0)).toBe("muted");
    expect(riskToColorKey(0.39)).toBe("muted");
    expect(riskToColorKey(-1)).toBe("muted");
  });
});

describe("riskToColor (with tokens)", () => {
  const tokens = {
    crit: "oklch(0.725 0.195 25)",
    warn: "oklch(0.815 0.155 80)",
    accent: "oklch(0.745 0.130 283)",
    text3: "oklch(0.620 0.010 250)",
  };

  it("maps crit risk to crit token", () => {
    expect(riskToColor(0.9, tokens)).toBe(tokens.crit);
  });

  it("maps warn risk to warn token", () => {
    expect(riskToColor(0.7, tokens)).toBe(tokens.warn);
  });

  it("maps accent risk to accent token", () => {
    expect(riskToColor(0.5, tokens)).toBe(tokens.accent);
  });

  it("maps muted risk to text3 token", () => {
    expect(riskToColor(0.2, tokens)).toBe(tokens.text3);
  });
});

// --------------------------------------------------------------------------
describe("storeRelationsToCyElements", () => {
  it("returns empty arrays for empty input", () => {
    const { nodes, edges } = storeRelationsToCyElements([], []);
    expect(nodes).toEqual([]);
    expect(edges).toEqual([]);
  });

  it("converts entities to cy node elements", () => {
    const entity = makeEntity();
    const { nodes } = storeRelationsToCyElements([entity], []);
    expect(nodes).toHaveLength(1);
    const node = nodes[0] as CyNode;
    expect(node.group).toBe("nodes");
    expect(node.data.id).toBe("uuid-001");
    expect(node.data.label).toBe("web-04");
    expect(node.data.entityType).toBe("host");
    expect(node.data.riskScore).toBe(0.5);
    expect(node.data.eventCount).toBe(100);
    expect(node.data.alertCount).toBe(1);
  });

  it("assigns risk color key correctly on node data", () => {
    const critEntity = makeEntity({ risk_score: 0.9 });
    const warnEntity = makeEntity({ entity_uuid: "uuid-w", risk_score: 0.7 });
    const accentEntity = makeEntity({ entity_uuid: "uuid-a", risk_score: 0.5 });
    const mutedEntity = makeEntity({ entity_uuid: "uuid-m", risk_score: 0.2 });

    const { nodes } = storeRelationsToCyElements(
      [critEntity, warnEntity, accentEntity, mutedEntity],
      [],
    );

    expect((nodes[0] as CyNode).data.colorKey).toBe("crit");
    expect((nodes[1] as CyNode).data.colorKey).toBe("warn");
    expect((nodes[2] as CyNode).data.colorKey).toBe("accent");
    expect((nodes[3] as CyNode).data.colorKey).toBe("muted");
  });

  it("converts relations to cy edge elements", () => {
    const relation = makeRelation();
    const { edges } = storeRelationsToCyElements([], [relation]);
    expect(edges).toHaveLength(1);
    const edge = edges[0] as CyEdge;
    expect(edge.group).toBe("edges");
    expect(edge.data.source).toBe("uuid-001");
    expect(edge.data.target).toBe("uuid-002");
    expect(edge.data.relationType).toBe("logged_into");
    expect(edge.data.severity).toBe(0.5);
  });

  it("edge id is deterministic (source_target)", () => {
    const rel = makeRelation({ source_uuid: "a", target_uuid: "b" });
    const { edges } = storeRelationsToCyElements([], [rel]);
    expect((edges[0] as CyEdge).data.id).toBe("a_b");
  });

  it("deduplicates edges with same source/target pair", () => {
    const rel1 = makeRelation({ source_uuid: "a", target_uuid: "b", relation_type: "logged_into" });
    const rel2 = makeRelation({ source_uuid: "a", target_uuid: "b", relation_type: "accessed" });
    const { edges } = storeRelationsToCyElements([], [rel1, rel2]);
    expect(edges).toHaveLength(1);
  });

  it("handles multiple nodes and edges correctly", () => {
    const entities = [
      makeEntity({ entity_uuid: "n1", entity_value: "node1", risk_score: 0.9 }),
      makeEntity({ entity_uuid: "n2", entity_value: "node2", risk_score: 0.5 }),
      makeEntity({ entity_uuid: "n3", entity_value: "node3", risk_score: 0.1 }),
    ];
    const relations = [
      makeRelation({ source_uuid: "n1", target_uuid: "n2" }),
      makeRelation({ source_uuid: "n2", target_uuid: "n3" }),
    ];

    const { nodes, edges } = storeRelationsToCyElements(entities, relations);
    expect(nodes).toHaveLength(3);
    expect(edges).toHaveLength(2);
  });

  it("does not mutate input arrays", () => {
    const entities = [makeEntity()];
    const relations = [makeRelation()];
    const origEntities = [...entities];
    const origRelations = [...relations];
    storeRelationsToCyElements(entities, relations);
    expect(entities).toEqual(origEntities);
    expect(relations).toEqual(origRelations);
  });

  it("node size is scaled by event_count", () => {
    const small = makeEntity({ event_count: 0, risk_score: 0.5 });
    const large = makeEntity({ entity_uuid: "l", event_count: 10000, risk_score: 0.5 });
    const { nodes } = storeRelationsToCyElements([small, large], []);
    const sn = (nodes[0] as CyNode).data.size;
    const ln = (nodes[1] as CyNode).data.size;
    expect(ln).toBeGreaterThan(sn);
  });
});
