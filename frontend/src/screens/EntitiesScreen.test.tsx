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
vi.mock("@/stores/entity", () => ({
  useEntityStore: (sel: (s: typeof STORE) => unknown) => sel(STORE),
}));

import { EntitiesScreen } from "./EntitiesScreen";

describe("EntitiesScreen drill (S-326)", () => {
  beforeEach(() => {
    lastProps = null;
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
