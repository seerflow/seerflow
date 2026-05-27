import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, act, waitFor } from "@testing-library/react";
import { createRef } from "react";

// --------------------------------------------------------------------------
// Mock cytoscape — tests check wrapper behavior, not layout algorithms
// --------------------------------------------------------------------------
const mockDestroy = vi.fn();
const mockLayoutRun = vi.fn();
const mockLayout = vi.fn(() => ({ run: mockLayoutRun }));
const mockFit = vi.fn();
const mockAdd = vi.fn();
const mockRemove = vi.fn();
const mockElements = vi.fn(() => ({ remove: mockRemove }));
const mockOn = vi.fn();
const mockStyle = vi.fn(() => ({ update: vi.fn() }));
const mockUnselect = vi.fn();
const mockEleSelect = vi.fn();
const mockDollar = vi.fn(() => ({ unselect: mockUnselect }));
const mockGetElementById = vi.fn(() => ({ select: mockEleSelect, length: 1 }));
const mockZoom = vi.fn((arg?: unknown) => (arg === undefined ? 2 : undefined));
const mockCenter = vi.fn();

const mockCyInstance = {
  destroy: mockDestroy,
  layout: mockLayout,
  fit: mockFit,
  add: mockAdd,
  elements: mockElements,
  on: mockOn,
  style: mockStyle,
  $: mockDollar,
  getElementById: mockGetElementById,
  zoom: mockZoom,
  center: mockCenter,
  id: "root",
};

const mockCytoscape = vi.fn(() => mockCyInstance);
// cytoscape.use should be a no-op
(mockCytoscape as unknown as Record<string, unknown>).use = vi.fn();

vi.mock("cytoscape", () => ({ default: mockCytoscape }));
vi.mock("cytoscape-fcose", () => ({ default: vi.fn() }));
vi.mock("cytoscape-dagre", () => ({ default: vi.fn() }));

import type { GraphEntity, GraphRelation } from "./entityGraphAdapter";
import { EntityGraphCanvas } from "./EntityGraphCanvas";
import type { EntityGraphCanvasHandle } from "./EntityGraphCanvas";

// --------------------------------------------------------------------------
const makeNodes = (): GraphEntity[] => [
  { entity_uuid: "n1", entity_type: "host", entity_value: "web-04", risk_score: 0.71, event_count: 100, alert_count: 1 },
  { entity_uuid: "n2", entity_type: "user", entity_value: "root", risk_score: 0.94, event_count: 500, alert_count: 3 },
];
const makeEdges = (): GraphRelation[] => [
  { source_uuid: "n1", target_uuid: "n2", relation_type: "logged_into", severity: 0.8 },
];

// --------------------------------------------------------------------------
describe("EntityGraphCanvas", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Restore use as a no-op after clearAllMocks
    (mockCytoscape as unknown as Record<string, unknown>).use = vi.fn();
  });

  it("renders a container div", () => {
    const { container } = render(<EntityGraphCanvas nodes={[]} edges={[]} />);
    expect(container.firstChild).toBeTruthy();
  });

  it("creates a cytoscape instance on mount (async load)", async () => {
    render(<EntityGraphCanvas nodes={makeNodes()} edges={makeEdges()} />);
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalledOnce(), { timeout: 2000 });
  });

  it("destroys cytoscape on unmount", async () => {
    const { unmount } = render(<EntityGraphCanvas nodes={makeNodes()} edges={makeEdges()} />);
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalledOnce(), { timeout: 2000 });
    unmount();
    expect(mockDestroy).toHaveBeenCalledOnce();
  });

  it("does NOT re-create the cy instance when nodes/edges props change", async () => {
    const { rerender } = render(<EntityGraphCanvas nodes={makeNodes()} edges={makeEdges()} />);
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalledOnce(), { timeout: 2000 });
    await act(async () => { rerender(<EntityGraphCanvas nodes={[]} edges={[]} />); });
    await act(async () => { rerender(<EntityGraphCanvas nodes={makeNodes()} edges={makeEdges()} />); });
    expect(mockCytoscape).toHaveBeenCalledTimes(1);
  });

  it("passes layout option to cytoscape constructor on mount", async () => {
    render(<EntityGraphCanvas nodes={makeNodes()} edges={makeEdges()} />);
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalledOnce(), { timeout: 2000 });
    const opts = (mockCytoscape.mock.calls[0] as unknown as [{ layout: { name: string } }])[0];
    // Default layout is Force → fcose
    expect(opts.layout).toEqual(expect.objectContaining({ name: "fcose" }));
  });

  it("accepts layout prop Hierarchy → dagre in constructor opts", async () => {
    render(<EntityGraphCanvas nodes={makeNodes()} edges={makeEdges()} layout="Hierarchy" />);
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalledOnce(), { timeout: 2000 });
    const opts = (mockCytoscape.mock.calls[0] as unknown as [{ layout: { name: string } }])[0];
    expect(opts.layout).toEqual(expect.objectContaining({ name: "dagre" }));
  });

  it("accepts Force layout → fcose in constructor opts", async () => {
    render(<EntityGraphCanvas nodes={makeNodes()} edges={makeEdges()} layout="Force" />);
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalledOnce(), { timeout: 2000 });
    const opts = (mockCytoscape.mock.calls[0] as unknown as [{ layout: { name: string } }])[0];
    expect(opts.layout).toEqual(expect.objectContaining({ name: "fcose" }));
  });

  it("accepts Radial layout → concentric in constructor opts", async () => {
    render(<EntityGraphCanvas nodes={makeNodes()} edges={makeEdges()} layout="Radial" />);
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalledOnce(), { timeout: 2000 });
    const opts = (mockCytoscape.mock.calls[0] as unknown as [{ layout: { name: string } }])[0];
    expect(opts.layout).toEqual(expect.objectContaining({ name: "concentric" }));
  });

  it("accepts optional className prop", () => {
    const { container } = render(<EntityGraphCanvas nodes={[]} edges={[]} className="sf-graph" />);
    expect(container.firstChild).toHaveClass("sf-graph");
  });

  it("calls fit when fitOnChange is true and elements change", async () => {
    const { rerender } = render(<EntityGraphCanvas nodes={[]} edges={[]} fitOnChange />);
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalledOnce(), { timeout: 2000 });
    await act(async () => {
      rerender(<EntityGraphCanvas nodes={makeNodes()} edges={makeEdges()} fitOnChange />);
    });
    expect(mockFit).toHaveBeenCalled();
  });

  // ── Selection ring (S-326 AC1) ─────────────────────────────────────────
  it("applies selection to the matching node when selectedUuid is set", async () => {
    const { rerender } = render(<EntityGraphCanvas nodes={makeNodes()} edges={makeEdges()} />);
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalledOnce(), { timeout: 2000 });
    await act(async () => {
      rerender(<EntityGraphCanvas nodes={makeNodes()} edges={makeEdges()} selectedUuid="n2" />);
    });
    expect(mockGetElementById).toHaveBeenCalledWith("n2");
    expect(mockEleSelect).toHaveBeenCalled();
  });

  it("clears prior selection before selecting (and when selectedUuid is null)", async () => {
    const { rerender } = render(
      <EntityGraphCanvas nodes={makeNodes()} edges={makeEdges()} selectedUuid="n1" />,
    );
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalledOnce(), { timeout: 2000 });
    await act(async () => {
      rerender(<EntityGraphCanvas nodes={makeNodes()} edges={makeEdges()} selectedUuid={null} />);
    });
    expect(mockDollar).toHaveBeenCalledWith(":selected");
    expect(mockUnselect).toHaveBeenCalled();
  });

  // ── Double-click drill (S-326 AC2) ─────────────────────────────────────
  it("fires onNodeDblClick with the node id on dbltap", async () => {
    const onNodeDblClick = vi.fn();
    render(
      <EntityGraphCanvas nodes={makeNodes()} edges={makeEdges()} onNodeDblClick={onNodeDblClick} />,
    );
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalledOnce(), { timeout: 2000 });
    const call = mockOn.mock.calls.find((c) => c[0] === "dbltap" && c[1] === "node");
    expect(call).toBeDefined();
    const handler = call![2] as (e: { target: { id: () => string } }) => void;
    handler({ target: { id: () => "n2" } });
    expect(onNodeDblClick).toHaveBeenCalledWith("n2");
  });

  // ── Imperative zoom/fit/fullscreen handle (S-326 AC3) ──────────────────
  it("exposes imperative zoomIn/zoomOut/fit/fullscreen via ref", async () => {
    const ref = createRef<EntityGraphCanvasHandle>();
    render(<EntityGraphCanvas ref={ref} nodes={makeNodes()} edges={makeEdges()} />);
    await waitFor(() => expect(mockCytoscape).toHaveBeenCalledOnce(), { timeout: 2000 });
    expect(ref.current).not.toBeNull();
    act(() => ref.current!.fit());
    expect(mockFit).toHaveBeenCalled();
    act(() => ref.current!.zoomIn());
    act(() => ref.current!.zoomOut());
    // zoom() called as getter (no-arg) then setter (object)
    expect(mockZoom).toHaveBeenCalled();
    // fullscreen guarded — should not throw even without requestFullscreen
    expect(() => act(() => ref.current!.fullscreen())).not.toThrow();
  });
});
