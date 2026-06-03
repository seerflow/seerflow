/**
 * EntitiesScreen drill tests (S-326).
 *
 * The store and the EntityExplorerGraph wrapper are mocked so we can assert
 * the graph data + drill props EntitiesScreen computes. Depth-1 drill filters
 * the focal entity + its direct neighbours; clearing restores the full graph.
 */
import { render, screen, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import type { GraphEntity, GraphRelation } from "@/viz/entityGraphAdapter";

// Capture the props EntitiesScreen passes to EntityExplorerGraph
let lastProps:
  | {
      nodes: GraphEntity[];
      edges: GraphRelation[];
      drillActive?: boolean;
      onNodeDblClick: (id: string) => void;
      onClearDrill?: () => void;
    }
  | null = null;

vi.mock("@/components/EntityExplorer/EntityExplorerGraph", () => ({
  EntityExplorerGraph: (p: {
    nodes: GraphEntity[];
    edges: GraphRelation[];
    drillActive?: boolean;
    onNodeDblClick: (id: string) => void;
    onClearDrill?: () => void;
  }) => {
    lastProps = p;
    return (
      <div
        data-testid="entity-explorer-graph"
        data-nodes={p.nodes.length}
        data-edges={p.edges.length}
        data-drill={p.drillActive ? "1" : "0"}
      />
    );
  },
}));

// Store with a focal entity + 2 related (depth-1) neighbours.
const STORE = {
  restoreFromHash: vi.fn(),
  clearSelection: vi.fn(),
  selectEntity: vi.fn(),
  setRange: vi.fn(),
  selectedEntityUuid: "focal",
  selectedEntityType: "user",
  selectedEntityValue: "root",
  related: [
    { entity_uuid: "rel1", entity_type: "host", entity_value: "web-04", relation_type: "logged_into" },
    { entity_uuid: "rel2", entity_type: "ip", entity_value: "10.0.0.1", relation_type: "has_ip" },
  ],
  events: [],
  searchResults: [],
  recent: [],
};

// Mutable holder so individual tests can swap the mocked store snapshot.
let currentStore: Record<string, unknown> = STORE;
vi.mock("@/stores/entity", () => ({
  useEntityStore: (sel: (s: Record<string, unknown>) => unknown) => sel(currentStore),
}));

import { EntitiesScreen } from "./EntitiesScreen";

describe("EntitiesScreen focal stats (S-328)", () => {
  beforeEach(() => {
    lastProps = null;
    currentStore = STORE;
  });

  it("passes computed risk / event-count / alert-count for the focal node", () => {
    currentStore = {
      ...STORE,
      events: [
        { event_id: "ev1", timestamp_ns: 0n, source_type: "s", severity_id: 2, message: "m", related_ips: [], related_users: [], related_hosts: [], related_domains: [] },
        { event_id: "ev2", timestamp_ns: 0n, source_type: "s", severity_id: 5, message: "m", related_ips: [], related_users: [], related_hosts: [], related_domains: [] },
      ],
      total: 1_204,
      riskHistory: [
        { bucket_start_ns: "0", points: 0, alert_count: 3, top_rule_name: "" },
        { bucket_start_ns: "0", points: 0, alert_count: 1, top_rule_name: "" },
      ],
    };

    render(<EntitiesScreen />);
    expect(lastProps).not.toBeNull();
    const focal = lastProps!.nodes.find((n) => n.entity_uuid === "focal");
    expect(focal).toBeDefined();
    expect(focal!.event_count).toBe(1_204);
    expect(focal!.alert_count).toBe(4);
    expect(focal!.risk_score).toBeCloseTo(5 / 6, 5);
  });
});

describe("EntitiesScreen drill (S-326)", () => {
  beforeEach(() => {
    lastProps = null;
    currentStore = STORE;
  });

  it("passes the full graph (focal + related) by default, drill inactive", () => {
    render(<EntitiesScreen />);
    const g = screen.getByTestId("entity-explorer-graph");
    expect(g).toHaveAttribute("data-nodes", "3"); // focal + rel1 + rel2
    expect(g).toHaveAttribute("data-drill", "0");
  });

  it("drilling filters to node + depth-1 neighbours, then restores", () => {
    render(<EntitiesScreen />);
    expect(lastProps).not.toBeNull();

    // Drill into rel1 → keep rel1 + focal (focal→rel1 edge); rel2 dropped.
    act(() => lastProps!.onNodeDblClick("rel1"));
    let g = screen.getByTestId("entity-explorer-graph");
    expect(g).toHaveAttribute("data-nodes", "2"); // focal + rel1
    expect(g).toHaveAttribute("data-drill", "1");

    // Restore the full graph.
    act(() => lastProps!.onClearDrill!());
    g = screen.getByTestId("entity-explorer-graph");
    expect(g).toHaveAttribute("data-nodes", "3");
    expect(g).toHaveAttribute("data-drill", "0");
  });
});
