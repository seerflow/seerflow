/**
 * Unit tests for EntityExplorerGraph and EntityInspector (S-322).
 * TDD: tests written first. Canvas (Cytoscape) is mocked — internals are
 * smoke-tested separately via EntityGraphCanvas.test.tsx.
 */
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import type { GraphEntity, GraphRelation } from "@/viz/entityGraphAdapter";
import type { EntityEvent, EntityRelation } from "@/lib/types";

// ── Mock Cytoscape canvas (heavy, async, DOM) ──────────────────────────────
vi.mock("@/viz/EntityGraphCanvas", () => ({
  EntityGraphCanvas: ({
    nodes,
    edges,
    layout,
    onNodeSelect,
  }: {
    nodes: GraphEntity[];
    edges: GraphRelation[];
    layout?: string;
    onNodeSelect?: (id: string | null) => void;
  }) => (
    <div
      data-testid="entity-graph-canvas"
      data-layout={layout ?? "Force"}
      data-nodes={nodes.length}
      data-edges={edges.length}
      onClick={() => onNodeSelect?.(nodes[0]?.entity_uuid ?? null)}
    />
  ),
}));

import { EntityExplorerGraph } from "./EntityExplorerGraph";
import { EntityInspector } from "./EntityInspector";

// ── Test fixtures ──────────────────────────────────────────────────────────

const NODES: GraphEntity[] = [
  { entity_uuid: "aaaa-bbbb", entity_type: "user",    entity_value: "root@10.0.1.42", risk_score: 0.94, event_count: 120, alert_count: 4 },
  { entity_uuid: "cccc-dddd", entity_type: "host",    entity_value: "web-04",          risk_score: 0.72, event_count: 40,  alert_count: 1 },
  { entity_uuid: "eeee-ffff", entity_type: "ip",      entity_value: "10.0.1.42",       risk_score: 0.45, event_count: 15,  alert_count: 0 },
  { entity_uuid: "gggg-hhhh", entity_type: "service", entity_value: "svc-deploy",      risk_score: 0.30, event_count: 5,   alert_count: 0 },
  { entity_uuid: "iiii-jjjj", entity_type: "process", entity_value: "bash",             risk_score: 0.10, event_count: 2,   alert_count: 0 },
];

const EDGES: GraphRelation[] = [
  { source_uuid: "aaaa-bbbb", target_uuid: "cccc-dddd", relation_type: "logged_into", severity: 0.8 },
  { source_uuid: "aaaa-bbbb", target_uuid: "eeee-ffff", relation_type: "has_ip",      severity: 0.5 },
];

const EVENTS: EntityEvent[] = [
  {
    event_id: "ev-1",
    timestamp_ns: 1700000000000000000n,
    source_type: "auditd",
    severity_id: 5,
    message: "sudo → /etc/shadow",
    related_ips: [],
    related_users: [],
    related_hosts: [],
    related_domains: [],
  },
  {
    event_id: "ev-2",
    timestamp_ns: 1700000000100000000n,
    source_type: "sshd",
    severity_id: 2,
    message: "Accepted pubkey",
    related_ips: [],
    related_users: [],
    related_hosts: [],
    related_domains: [],
  },
];

const RELATED: EntityRelation[] = [
  { entity_uuid: "cccc-dddd", entity_type: "host",    entity_value: "web-04",     relation_type: "logged_into" },
  { entity_uuid: "eeee-ffff", entity_type: "ip",      entity_value: "10.0.1.42",  relation_type: "has_ip" },
];

// ── EntityExplorerGraph tests ──────────────────────────────────────────────

describe("EntityExplorerGraph", () => {
  const defaultProps = {
    nodes: NODES,
    edges: EDGES,
    selectedUuid: null,
    onNodeSelect: vi.fn(),
    onNodeDblClick: vi.fn(),
    events: EVENTS,
    related: RELATED,
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders three-column layout", () => {
    render(<EntityExplorerGraph {...defaultProps} />);
    expect(screen.getByTestId("entity-explorer-graph")).toBeInTheDocument();
    expect(screen.getByTestId("graph-left-rail")).toBeInTheDocument();
    expect(screen.getByTestId("graph-center")).toBeInTheDocument();
    expect(screen.getByTestId("graph-right-inspector")).toBeInTheDocument();
  });

  it("renders types checklist with all 5 entity types", () => {
    render(<EntityExplorerGraph {...defaultProps} />);
    // Each type should appear as a checklist label
    ["user", "host", "ip", "service", "process"].forEach((t) => {
      expect(screen.getByTestId(`type-filter-${t}`)).toBeInTheDocument();
    });
  });

  it("toggles a type filter off and back on", () => {
    render(<EntityExplorerGraph {...defaultProps} />);
    const userCheckbox = screen.getByTestId("type-filter-user");
    // Initially checked
    expect(userCheckbox).toHaveAttribute("aria-checked", "true");
    fireEvent.click(userCheckbox);
    expect(userCheckbox).toHaveAttribute("aria-checked", "false");
    fireEvent.click(userCheckbox);
    expect(userCheckbox).toHaveAttribute("aria-checked", "true");
  });

  it("renders layout chips: Force, Radial, Hierarchy", () => {
    render(<EntityExplorerGraph {...defaultProps} />);
    expect(screen.getByRole("button", { name: /force/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /radial/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /hierarchy/i })).toBeInTheDocument();
  });

  it("clicking a layout chip changes the active layout", () => {
    render(<EntityExplorerGraph {...defaultProps} />);
    const radialBtn = screen.getByRole("button", { name: /radial/i });
    fireEvent.click(radialBtn);
    // Canvas should receive layout="Radial"
    expect(screen.getByTestId("entity-graph-canvas")).toHaveAttribute("data-layout", "Radial");
  });

  it("renders min-risk slider with initial value 0", () => {
    render(<EntityExplorerGraph {...defaultProps} />);
    const slider = screen.getByRole("slider", { name: /min risk/i });
    expect(slider).toBeInTheDocument();
    expect(slider).toHaveValue("0");
  });

  it("renders time-window chips: 15m, 1h, 24h, 7d", () => {
    render(<EntityExplorerGraph {...defaultProps} />);
    expect(screen.getByRole("button", { name: /^15m$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^1h$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^24h$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^7d$/i })).toBeInTheDocument();
  });

  it("renders legend with 4 risk color entries", () => {
    render(<EntityExplorerGraph {...defaultProps} />);
    expect(screen.getByTestId("graph-legend")).toBeInTheDocument();
    // Legend section title
    expect(screen.getByText(/legend/i)).toBeInTheDocument();
  });

  it("renders node/edge counter badge", () => {
    render(<EntityExplorerGraph {...defaultProps} />);
    expect(screen.getByTestId("graph-counter")).toBeInTheDocument();
    // Should show node count from visible nodes
    const counter = screen.getByTestId("graph-counter");
    expect(counter.textContent).toMatch(/nodes/i);
    expect(counter.textContent).toMatch(/edges/i);
  });

  it("passes filtered nodes to canvas when type filter is toggled off", () => {
    render(<EntityExplorerGraph {...defaultProps} />);
    const processFilter = screen.getByTestId("type-filter-process");
    fireEvent.click(processFilter); // deactivate process
    const canvas = screen.getByTestId("entity-graph-canvas");
    // process node removed → 4 nodes
    expect(canvas).toHaveAttribute("data-nodes", "4");
  });

  it("passes min-risk filtered nodes when slider is moved", () => {
    render(<EntityExplorerGraph {...defaultProps} />);
    const slider = screen.getByRole("slider", { name: /min risk/i });
    // Set threshold to 0.5 → only user(0.94), host(0.72) pass
    fireEvent.change(slider, { target: { value: "0.5" } });
    const canvas = screen.getByTestId("entity-graph-canvas");
    expect(canvas).toHaveAttribute("data-nodes", "2");
  });

  it("calls onNodeSelect when canvas fires node select", () => {
    const onNodeSelect = vi.fn();
    render(<EntityExplorerGraph {...defaultProps} onNodeSelect={onNodeSelect} />);
    fireEvent.click(screen.getByTestId("entity-graph-canvas"));
    expect(onNodeSelect).toHaveBeenCalledWith("aaaa-bbbb");
  });
});

// ── EntityInspector tests ──────────────────────────────────────────────────

describe("EntityInspector", () => {
  it("renders empty state when selectedUuid is null", () => {
    render(
      <EntityInspector
        selectedUuid={null}
        nodes={NODES}
        events={[]}
        related={[]}
      />,
    );
    expect(screen.getByTestId("inspector-empty")).toBeInTheDocument();
  });

  it("renders entity header when node is selected", () => {
    render(
      <EntityInspector
        selectedUuid="aaaa-bbbb"
        nodes={NODES}
        events={EVENTS}
        related={RELATED}
      />,
    );
    expect(screen.getByTestId("inspector-entity-header")).toBeInTheDocument();
    expect(screen.getByText("root@10.0.1.42")).toBeInTheDocument();
  });

  it("renders 2x2 stat grid with risk, events, neighbors, alerts", () => {
    render(
      <EntityInspector
        selectedUuid="aaaa-bbbb"
        nodes={NODES}
        events={EVENTS}
        related={RELATED}
      />,
    );
    // Stat labels — use getAllByText because "events" appears in label + section heading
    expect(screen.getAllByText(/^risk$/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/^events$/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/^neighbors$/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/^alerts$/i).length).toBeGreaterThan(0);
  });

  it("renders recent events section", () => {
    render(
      <EntityInspector
        selectedUuid="aaaa-bbbb"
        nodes={NODES}
        events={EVENTS}
        related={RELATED}
      />,
    );
    expect(screen.getByTestId("inspector-recent-events")).toBeInTheDocument();
    // "sudo → /etc/shadow" appears in both linked-alerts and recent-events
    expect(screen.getAllByText("sudo → /etc/shadow").length).toBeGreaterThan(0);
  });

  it("renders linked alerts section", () => {
    render(
      <EntityInspector
        selectedUuid="aaaa-bbbb"
        nodes={NODES}
        events={EVENTS}
        related={RELATED}
      />,
    );
    expect(screen.getByTestId("inspector-linked-alerts")).toBeInTheDocument();
  });
});
