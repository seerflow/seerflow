/**
 * EntityGraphCanvas — Cytoscape.js graph canvas component.
 *
 * Owns a cy instance in a ref (never recreated on prop change).
 * Cytoscape + layout plugins are lazily imported for code-splitting.
 *
 * Layout toggle: Force (fcose) / Radial (concentric) / Hierarchy (dagre).
 * Nodes colored by risk threshold.
 * Selected node gets a dashed --crit ring.
 * Zoom/pan/fit via Cytoscape's built-in handling.
 * Re-styles on seerflow-theme event via resolveTokens.
 */

import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import type { GraphEntity, GraphRelation } from "./entityGraphAdapter";
import { storeRelationsToCyElements, riskToColor } from "./entityGraphAdapter";
import { resolveTokens, subscribeToThemeChanges } from "@/lib/theme/resolveTokens";

// --------------------------------------------------------------------------
// Types
// --------------------------------------------------------------------------

export type GraphLayout = "Force" | "Radial" | "Hierarchy";

/** Imperative controls exposed via ref for the zoom/fit toolbar (S-326). */
export interface EntityGraphCanvasHandle {
  zoomIn: () => void;
  zoomOut: () => void;
  fit: () => void;
  fullscreen: () => void;
}

export interface EntityGraphCanvasProps {
  nodes: GraphEntity[];
  edges: GraphRelation[];
  layout?: GraphLayout;
  /** Auto-fit the viewport when nodes/edges change */
  fitOnChange?: boolean;
  onNodeSelect?: (id: string | null) => void;
  /** Fired on node double-tap — used to drill into the node's neighborhood */
  onNodeDblClick?: (id: string) => void;
  /** UUID of the node that should carry the selection ring; null/absent clears it */
  selectedUuid?: string | null;
  className?: string;
  width?: number;
  height?: number;
}

// --------------------------------------------------------------------------
// Layout name mapping
// --------------------------------------------------------------------------

const LAYOUT_NAMES: Record<GraphLayout, string> = {
  Force:     "fcose",
  Radial:    "concentric",
  Hierarchy: "dagre",
};

// --------------------------------------------------------------------------
// Component
// --------------------------------------------------------------------------

export const EntityGraphCanvas = forwardRef<
  EntityGraphCanvasHandle,
  EntityGraphCanvasProps
>(function EntityGraphCanvas(
  {
    nodes,
    edges,
    layout = "Force",
    fitOnChange = false,
    onNodeSelect,
    onNodeDblClick,
    selectedUuid,
    className,
    width = 760,
    height = 580,
  },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null);
  // cy is typed as `unknown` here to avoid importing cytoscape at module scope
  // (we want the lazy-import to drive actual bundling)
  const cyRef = useRef<unknown>(null);
  const layoutRef = useRef<GraphLayout>(layout);
  const nodesRef = useRef<GraphEntity[]>(nodes);
  const edgesRef = useRef<GraphRelation[]>(edges);
  const unsubThemeRef = useRef<(() => void) | null>(null);

  // ── Mount: lazy-load cytoscape and create instance ──────────────────────
  useEffect(() => {
    if (!containerRef.current) return;

    let destroyed = false;

    (async () => {
      // Dynamic imports for code-splitting
      const [
        { default: cytoscape },
        { default: fcose },
        { default: dagre },
      ] = await Promise.all([
        import("cytoscape"),
        import("cytoscape-fcose"),
        import("cytoscape-dagre"),
      ]);

      if (destroyed) return;

      // Register plugins once (idempotent)
      try { cytoscape.use(fcose); } catch { /* already registered */ }
      try { cytoscape.use(dagre); } catch { /* already registered */ }

      const tokens = resolveTokens();
      const { nodes: cyNodes, edges: cyEdges } =
        storeRelationsToCyElements(nodesRef.current, edgesRef.current);

      const cy = cytoscape({
        container: containerRef.current!,
        elements: [...cyNodes, ...cyEdges],
        style: buildStyle(tokens),
        layout: { name: LAYOUT_NAMES[layoutRef.current] },
        userZoomingEnabled: true,
        userPanningEnabled: true,
        boxSelectionEnabled: false,
      });

      // Node select handler
      cy.on("tap", "node", (evt: { target: { id: () => string } }) => {
        onNodeSelect?.(evt.target.id());
      });
      // Node double-click → neighborhood drill (S-326)
      cy.on("dbltap", "node", (evt: { target: { id: () => string } }) => {
        onNodeDblClick?.(evt.target.id());
      });
      cy.on("tap", (evt: { target: unknown }) => {
        // Background tap: target is the cy core itself
        if (!(evt.target as { isNode?: () => boolean }).isNode?.()) {
          onNodeSelect?.(null);
        }
      });

      cyRef.current = cy;

      // Re-style on theme change
      unsubThemeRef.current = subscribeToThemeChanges((t) => {
        (cy as { style: (s: unknown) => { update: () => void } })
          .style(buildStyle(t))
          .update();
      });
    })();

    return () => {
      destroyed = true;
      unsubThemeRef.current?.();
      unsubThemeRef.current = null;
      if (cyRef.current) {
        (cyRef.current as { destroy: () => void }).destroy();
        cyRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // mount only

  // ── Elements update (no re-create) ──────────────────────────────────────
  useEffect(() => {
    nodesRef.current = nodes;
    edgesRef.current = edges;
    const cy = cyRef.current;
    if (!cy) return;

    const { nodes: cyNodes, edges: cyEdges } =
      storeRelationsToCyElements(nodes, edges);

    const cytoscapeLike = cy as {
      elements: () => { remove: () => void };
      add: (els: unknown[]) => void;
      layout: (opts: { name: string }) => { run: () => void };
      fit: () => void;
    };

    cytoscapeLike.elements().remove();
    cytoscapeLike.add([...cyNodes, ...cyEdges]);
    cytoscapeLike.layout({ name: LAYOUT_NAMES[layoutRef.current] }).run();

    if (fitOnChange) {
      cytoscapeLike.fit();
    }
  }, [nodes, edges, fitOnChange]);

  // ── Layout change ────────────────────────────────────────────────────────
  useEffect(() => {
    layoutRef.current = layout;
    const cy = cyRef.current;
    if (!cy) return;
    (cy as { layout: (opts: { name: string }) => { run: () => void } })
      .layout({ name: LAYOUT_NAMES[layout] })
      .run();
  }, [layout]);

  // ── Selection ring (S-326) ───────────────────────────────────────────────
  useEffect(() => {
    const cy = cyRef.current as {
      $: (sel: string) => { unselect: () => void };
      getElementById: (id: string) => { select: () => void; length: number };
    } | null;
    if (!cy) return;
    cy.$(":selected").unselect();
    if (selectedUuid) {
      const ele = cy.getElementById(selectedUuid);
      if (ele.length > 0) ele.select();
    }
    // Depend on `nodes` too so the ring re-applies after elements are re-added.
  }, [selectedUuid, nodes]);

  // ── Imperative zoom/fit/fullscreen controls (S-326) ──────────────────────
  const ZOOM_STEP = 1.25;
  useImperativeHandle(
    ref,
    (): EntityGraphCanvasHandle => ({
      zoomIn: () => {
        const cy = cyRef.current as { zoom: (o?: { level: number }) => number } | null;
        if (!cy) return;
        const current = cy.zoom();
        cy.zoom({ level: current * ZOOM_STEP });
      },
      zoomOut: () => {
        const cy = cyRef.current as { zoom: (o?: { level: number }) => number } | null;
        if (!cy) return;
        const current = cy.zoom();
        cy.zoom({ level: current / ZOOM_STEP });
      },
      fit: () => (cyRef.current as { fit?: () => void } | null)?.fit?.(),
      fullscreen: () => {
        const el = containerRef.current as
          | (HTMLDivElement & { requestFullscreen?: () => Promise<void> })
          | null;
        void el?.requestFullscreen?.();
      },
    }),
    [],
  );

  return (
    <div
      ref={containerRef}
      className={className}
      style={{ width, height, position: "relative" }}
    />
  );
});

// --------------------------------------------------------------------------
// Style builder — maps ThemeTokens to Cytoscape style array
// --------------------------------------------------------------------------

function buildStyle(tokens: ReturnType<typeof resolveTokens>) {
  return [
    {
      selector: "node",
      style: {
        "background-color": (ele: { data: (k: string) => number }) =>
          riskToColor(ele.data("riskScore") ?? 0, tokens),
        "border-color": (ele: { data: (k: string) => number }) =>
          riskToColor(ele.data("riskScore") ?? 0, tokens),
        "border-width": 1,
        "width": (ele: { data: (k: string) => number }) => ele.data("size") ?? 12,
        "height": (ele: { data: (k: string) => number }) => ele.data("size") ?? 12,
        "label": (ele: { data: (k: string) => string }) => ele.data("label") ?? "",
        "font-size": 10,
        "font-family": "var(--font-mono)",
        "color": tokens.text2,
        "text-valign": "bottom" as const,
        "text-margin-y": 4,
        "opacity": 0.9,
      },
    },
    {
      selector: "node:selected",
      style: {
        "border-color": tokens.crit,
        "border-width": 2,
        "border-style": "dashed" as const,
      },
    },
    {
      selector: "edge",
      style: {
        "line-color": tokens.line2,
        "width": 1,
        "opacity": 0.6,
        "curve-style": "bezier" as const,
      },
    },
    {
      selector: "edge[severity > 0.6]",
      style: {
        "line-color": tokens.warn,
        "width": 1.5,
        "opacity": 0.8,
      },
    },
    {
      selector: "edge[severity > 0.8]",
      style: {
        "line-color": tokens.crit,
        "width": 2,
        "opacity": 0.9,
      },
    },
  ];
}
