import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCenter,
  forceCollide,
  type Simulation,
  type ForceCenter,
} from "d3-force";
import type { EntityRelation } from "@/lib/types";
import { entitySourceColor } from "@/lib/entitySourceColor";
import { Button } from "@/components/ui/button";
import {
  INITIAL_VIEW,
  viewportReducer,
  type Viewport,
} from "./viewportReducer";

interface FocalNode { uuid: string; label: string; type: string; }

interface Props {
  focal: FocalNode;
  related: EntityRelation[];
  onNavigate: (uuid: string) => void;
}

interface SimNode {
  id: string;
  label: string;
  type: string;
  focal?: boolean;
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
  fx?: number | null;
  fy?: number | null;
}

interface SimLink {
  source: string | SimNode;
  target: string | SimNode;
  relation: string;
}

type Tip = {
  x: number;
  y: number;
  type: string;
  value: string;
  relation?: string;
} | null;

type DragState = {
  kind: "pan" | "node" | null;
  nodeId: string | null;
  pointerId: number;
  downX: number;
  downY: number;
  lastX: number;
  lastY: number;
  startTx: number;
  startTy: number;
  moved: boolean;
};

const MAX_NODES = 100;
const DRAG_THRESHOLD_PX = 4;
const KEY_PAN_PX = 24;
const ZOOM_KEY_FACTOR = 1.2;
const NEW_NODE_JITTER_PX = 10;

const noDrag: DragState = {
  kind: null,
  nodeId: null,
  pointerId: -1,
  downX: 0,
  downY: 0,
  lastX: 0,
  lastY: 0,
  startTx: 0,
  startTy: 0,
  moved: false,
};

function snapshotPositions(nodes: SimNode[]): Record<string, { x: number; y: number }> {
  const out: Record<string, { x: number; y: number }> = {};
  for (const n of nodes) out[n.id] = { x: n.x ?? 0, y: n.y ?? 0 };
  return out;
}

function toGraphCoords(
  clientX: number,
  clientY: number,
  view: Viewport,
  rect: DOMRect,
): { x: number; y: number } {
  return {
    x: (clientX - rect.left - view.tx) / view.scale,
    y: (clientY - rect.top - view.ty) / view.scale,
  };
}

export function EntityGraph({ focal, related, onNavigate }: Props) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const simRef = useRef<Simulation<SimNode, SimLink> | null>(null);
  const positionsRef = useRef<Record<string, { x: number; y: number }>>({});
  const dragRef = useRef<DragState>({ ...noDrag });
  const viewRef = useRef<Viewport>(INITIAL_VIEW);

  const [view, dispatch] = useReducer(viewportReducer, INITIAL_VIEW);
  viewRef.current = view;

  const [size, setSize] = useState({ w: 400, h: 320 });
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>({});
  const [tip, setTip] = useState<Tip>(null);
  const [dragKind, setDragKind] = useState<"pan" | "node" | null>(null);

  const truncated = related.length > MAX_NODES;
  const rendered = useMemo(
    () => (truncated ? related.slice(0, MAX_NODES) : related),
    [related, truncated],
  );

  // ResizeObserver — update size; centre force is updated below in a separate effect.
  useEffect(() => {
    const wrapper = wrapperRef.current;
    if (!wrapper) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        setSize({
          w: e.contentRect.width || 400,
          h: Math.max(240, e.contentRect.height || 320),
        });
      }
    });
    ro.observe(wrapper);
    return () => ro.disconnect();
  }, []);

  // Update centre force on size change without bumping alpha.
  useEffect(() => {
    const sim = simRef.current;
    if (!sim) return;
    const center = sim.force("center") as ForceCenter<SimNode> | undefined;
    if (center) {
      center.x(size.w / 2);
      center.y(size.h / 2);
    }
  }, [size.w, size.h]);

  // Build / rebuild the simulation when data changes.
  useEffect(() => {
    const prev = positionsRef.current;
    const w = size.w;
    const h = size.h;
    const focalNode: SimNode = {
      id: focal.uuid,
      label: focal.label,
      type: focal.type,
      focal: true,
      x: prev[focal.uuid]?.x ?? w / 2,
      y: prev[focal.uuid]?.y ?? h / 2,
      vx: 0,
      vy: 0,
      fx: w / 2,
      fy: h / 2, // pinned during warm-up
    };
    const satelliteNodes: SimNode[] = rendered.map((r) => {
      const known = prev[r.entity_uuid];
      const jx = (Math.random() - 0.5) * 2 * NEW_NODE_JITTER_PX;
      const jy = (Math.random() - 0.5) * 2 * NEW_NODE_JITTER_PX;
      return {
        id: r.entity_uuid,
        label: r.entity_value,
        type: r.entity_type,
        x: known?.x ?? w / 2 + jx,
        y: known?.y ?? h / 2 + jy,
        vx: 0,
        vy: 0,
      };
    });
    const nodes: SimNode[] = [focalNode, ...satelliteNodes];
    const links: SimLink[] = rendered.map((r) => ({
      source: focal.uuid,
      target: r.entity_uuid,
      relation: r.relation_type,
    }));

    // Tear down previous simulation.
    if (simRef.current) {
      simRef.current.on("tick", null);
      simRef.current.stop();
    }

    const sim: Simulation<SimNode, SimLink> = forceSimulation<SimNode, SimLink>(nodes)
      .force(
        "link",
        forceLink<SimNode, SimLink>(links)
          .id((d) => d.id)
          .distance(80),
      )
      .force("charge", forceManyBody<SimNode>().strength(-120))
      .force("center", forceCenter<SimNode>(w / 2, h / 2))
      .force("collide", forceCollide<SimNode>(18))
      .alpha(1);

    // Manual warm-up while alpha > 0.01 (capped at 300 ticks).
    sim.stop();
    for (let i = 0; i < 300 && sim.alpha() > 0.01; i++) sim.tick();

    // Unpin focal so it can drift naturally on subsequent user-driven alpha bumps.
    focalNode.fx = null;
    focalNode.fy = null;

    // Persistent tick listener. d3-force auto-stops when alpha < alphaMin (default 0.001).
    sim.on("tick", () => {
      const next = snapshotPositions(sim.nodes());
      positionsRef.current = next;
      setPositions(next);
    });

    // Snap once for first paint after warm-up.
    const initial = snapshotPositions(nodes);
    positionsRef.current = initial;
    setPositions(initial);
    simRef.current = sim;

    return () => {
      sim.on("tick", null);
      sim.stop();
    };
    // size.w / size.h only resize the centre force (separate effect); rebuilding on resize
    // would flash. Hence intentionally not in this dependency list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focal.uuid, focal.label, focal.type, rendered]);

  // Manual non-passive wheel listener.
  useEffect(() => {
    const el = wrapperRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      dispatch({
        kind: "wheelAt",
        deltaY: e.deltaY,
        ox: e.clientX - rect.left,
        oy: e.clientY - rect.top,
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const resetView = useCallback(() => {
    dispatch({ kind: "reset" });
    const sim = simRef.current;
    if (sim) {
      for (const n of sim.nodes()) {
        n.fx = null;
        n.fy = null;
      }
      sim.alpha(0.5).restart();
    }
  }, []);

  function onKeyDown(e: React.KeyboardEvent) {
    switch (e.key) {
      case "+":
      case "=":
        e.preventDefault();
        dispatch({ kind: "zoomBy", factor: ZOOM_KEY_FACTOR });
        break;
      case "-":
      case "_":
        e.preventDefault();
        dispatch({ kind: "zoomBy", factor: 1 / ZOOM_KEY_FACTOR });
        break;
      case "ArrowLeft":
        e.preventDefault();
        dispatch({ kind: "panBy", dx: KEY_PAN_PX, dy: 0 });
        break;
      case "ArrowRight":
        e.preventDefault();
        dispatch({ kind: "panBy", dx: -KEY_PAN_PX, dy: 0 });
        break;
      case "ArrowUp":
        e.preventDefault();
        dispatch({ kind: "panBy", dx: 0, dy: KEY_PAN_PX });
        break;
      case "ArrowDown":
        e.preventDefault();
        dispatch({ kind: "panBy", dx: 0, dy: -KEY_PAN_PX });
        break;
      case "0":
        e.preventDefault();
        resetView();
        break;
      case "Escape":
        (e.currentTarget as HTMLElement).blur();
        break;
      default:
        break;
    }
  }

  function onSvgPointerDown(e: React.PointerEvent<SVGSVGElement>) {
    // Node handlers call stopPropagation, so if this handler fires the event originated from background.
    e.currentTarget.setPointerCapture(e.pointerId);
    dragRef.current = {
      kind: "pan",
      nodeId: null,
      pointerId: e.pointerId,
      downX: e.clientX,
      downY: e.clientY,
      lastX: e.clientX,
      lastY: e.clientY,
      startTx: viewRef.current.tx,
      startTy: viewRef.current.ty,
      moved: false,
    };
    setDragKind("pan");
    setTip(null);
  }

  function onSvgPointerMove(e: React.PointerEvent<SVGSVGElement>) {
    const drag = dragRef.current;
    // pointerId may be undefined in jsdom (testing); fall back to kind check only.
    const pidMatch = e.pointerId == null || drag.pointerId === e.pointerId;
    if (drag.kind !== "pan" || !pidMatch) return;
    const totalDx = e.clientX - drag.downX;
    const totalDy = e.clientY - drag.downY;
    if (!drag.moved && Math.hypot(totalDx, totalDy) > DRAG_THRESHOLD_PX) drag.moved = true;
    // Dispatch incremental delta since last move event so panBy accumulates correctly.
    const dx = e.clientX - drag.lastX;
    const dy = e.clientY - drag.lastY;
    drag.lastX = e.clientX;
    drag.lastY = e.clientY;
    dispatch({ kind: "panBy", dx, dy });
  }

  function onSvgPointerUp(e: React.PointerEvent<SVGSVGElement>) {
    const drag = dragRef.current;
    const pidMatch = e.pointerId == null || drag.pointerId === e.pointerId;
    if (pidMatch) {
      try {
        e.currentTarget.releasePointerCapture(e.pointerId);
      } catch {
        // jsdom no-op
      }
      dragRef.current = { ...noDrag };
      setDragKind(null);
    }
  }

  function onNodePointerDown(
    e: React.PointerEvent<SVGGElement>,
    nodeId: string,
  ) {
    e.stopPropagation();
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    const sim = simRef.current;
    const node = sim?.nodes().find((n) => n.id === nodeId);
    if (node && !node.focal) {
      node.fx = node.x;
      node.fy = node.y;
      sim?.alphaTarget(0.3).restart();
    }
    dragRef.current = {
      kind: "node",
      nodeId,
      pointerId: e.pointerId,
      downX: e.clientX,
      downY: e.clientY,
      lastX: e.clientX,
      lastY: e.clientY,
      startTx: viewRef.current.tx,
      startTy: viewRef.current.ty,
      moved: false,
    };
    setDragKind("node");
    setTip(null);
  }

  function onNodePointerMove(
    e: React.PointerEvent<SVGGElement>,
    rel: EntityRelation,
  ) {
    const drag = dragRef.current;
    const pidMatchNode = e.pointerId == null || drag.pointerId === e.pointerId;
    if (drag.kind === "node" && drag.nodeId === rel.entity_uuid && pidMatchNode) {
      const dx = e.clientX - drag.downX;
      const dy = e.clientY - drag.downY;
      if (!drag.moved && Math.hypot(dx, dy) > DRAG_THRESHOLD_PX) drag.moved = true;
      const sim = simRef.current;
      const wrapper = wrapperRef.current;
      if (sim && wrapper) {
        const rect = wrapper.getBoundingClientRect();
        const gp = toGraphCoords(e.clientX, e.clientY, viewRef.current, rect);
        const node = sim.nodes().find((n) => n.id === rel.entity_uuid);
        if (node) {
          node.fx = gp.x;
          node.fy = gp.y;
        }
      }
      return;
    }
    // Tooltip mode (no active drag for this node).
    if (drag.kind === null) {
      const wrapper = wrapperRef.current;
      const rect = wrapper?.getBoundingClientRect() ?? new DOMRect(0, 0, 0, 0);
      setTip({
        x: e.clientX - rect.left,
        y: e.clientY - rect.top,
        type: rel.entity_type,
        value: rel.entity_value,
        relation: rel.relation_type,
      });
    }
  }

  function onNodePointerUp(
    e: React.PointerEvent<SVGGElement>,
    nodeId: string,
  ) {
    e.stopPropagation();
    const drag = dragRef.current;
    const pidMatchUp = e.pointerId == null || drag.pointerId === e.pointerId;
    if (drag.kind === "node" && drag.nodeId === nodeId && pidMatchUp) {
      const sim = simRef.current;
      if (sim) {
        const node = sim.nodes().find((n) => n.id === nodeId);
        if (node) {
          node.fx = null;
          node.fy = null;
        }
        sim.alphaTarget(0);
      }
      try {
        (e.currentTarget as Element).releasePointerCapture(e.pointerId);
      } catch {
        // jsdom no-op
      }
      // moved flag stays in drag state for the click handler below.
      const movedFlag = drag.moved;
      dragRef.current = { ...noDrag, moved: movedFlag };
      setDragKind(null);
    }
  }

  function onNodeClick(uuid: string) {
    const justDragged = dragRef.current.moved;
    dragRef.current = { ...noDrag };
    if (justDragged) return;
    onNavigate(uuid);
  }

  function onNodePointerLeave() {
    if (dragRef.current.kind === null) setTip(null);
  }

  const focalPos = positions[focal.uuid] ?? { x: size.w / 2, y: size.h / 2 };
  const ariaLabel = `Relationship graph for ${focal.label} with ${rendered.length} connections`;

  return (
    <div
      ref={wrapperRef}
      role="application"
      aria-roledescription="interactive relationship graph"
      aria-label="Entity relationship graph — use arrow keys to pan, plus and minus to zoom"
      tabIndex={0}
      onKeyDown={onKeyDown}
      className="relative h-full w-full min-h-0 flex flex-col overflow-hidden rounded-md border focus:outline-none focus:ring-2 focus:ring-ring"
    >
      {truncated && (
        <div className="z-10 bg-amber-100 px-2 py-1 text-xs text-amber-900 dark:bg-amber-900 dark:text-amber-100">
          Showing top 100 of {related.length} — click a neighbor to explore further.
        </div>
      )}
      <div className="flex justify-end px-2 py-1">
        <Button
          variant="ghost"
          size="sm"
          onClick={resetView}
          aria-label="Reset graph view"
        >
          Reset view
        </Button>
      </div>
      <svg
        ref={svgRef}
        role="img"
        aria-label={ariaLabel}
        width={size.w}
        height={size.h}
        className={`flex-1 min-h-0 block ${dragKind === "pan" ? "cursor-grabbing" : "cursor-grab"}`}
        onPointerDown={onSvgPointerDown}
        onPointerMove={onSvgPointerMove}
        onPointerUp={onSvgPointerUp}
        onPointerCancel={onSvgPointerUp}
      >
        <g transform={`translate(${view.tx} ${view.ty}) scale(${view.scale})`}>
          {rendered.map((r) => {
            const a = focalPos;
            const b = positions[r.entity_uuid];
            if (!b) return null;
            return (
              <g key={`link-${r.entity_uuid}`}>
                <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="currentColor" strokeOpacity={0.35} />
                <text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2} fontSize={9} fill="currentColor" opacity={0.6}>
                  {r.relation_type}
                </text>
              </g>
            );
          })}
          <g
            data-focal-id={focal.uuid}
            onPointerDown={(e) => {
              // Focal node is not draggable. Absorb the event so the SVG pan handler
              // does not treat this as a background click-drag.
              e.stopPropagation();
            }}
            onPointerMove={(e) => {
              if (dragRef.current.kind !== null) return;
              const wrapper = wrapperRef.current;
              if (!wrapper) return;
              const rect = wrapper.getBoundingClientRect();
              setTip({
                x: e.clientX - rect.left,
                y: e.clientY - rect.top,
                type: focal.type,
                value: focal.label,
              });
            }}
            onPointerLeave={() => {
              if (dragRef.current.kind === null) setTip(null);
            }}
          >
            <circle
              cx={focalPos.x}
              cy={focalPos.y}
              r={14}
              fill={entitySourceColor(`type:${focal.type}`)}
              stroke="currentColor"
              strokeWidth={2}
            />
            <text x={focalPos.x} y={focalPos.y + 26} textAnchor="middle" fontSize={11} fill="currentColor">
              {focal.label}
            </text>
          </g>
          {rendered.map((r) => {
            const p = positions[r.entity_uuid];
            if (!p) return null;
            return (
              <g
                key={r.entity_uuid}
                data-node-id={r.entity_uuid}
                onPointerDown={(e) => onNodePointerDown(e, r.entity_uuid)}
                onPointerMove={(e) => onNodePointerMove(e, r)}
                onPointerUp={(e) => onNodePointerUp(e, r.entity_uuid)}
                onPointerCancel={(e) => onNodePointerUp(e, r.entity_uuid)}
                onPointerLeave={onNodePointerLeave}
                onClick={() => onNodeClick(r.entity_uuid)}
                style={{ cursor: "pointer" }}
              >
                <circle cx={p.x} cy={p.y} r={10} fill={entitySourceColor(`type:${r.entity_type}`)} />
                <text x={p.x} y={p.y + 22} textAnchor="middle" fontSize={10} fill="currentColor">
                  {r.entity_value}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
      {rendered.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground">
          No related entities
        </div>
      )}
      {tip && (
        <div
          role="tooltip"
          aria-hidden="false"
          className="pointer-events-none absolute rounded border bg-popover px-2 py-1 text-xs text-popover-foreground shadow-md"
          style={{ left: tip.x + 12, top: tip.y + 12 }}
        >
          {tip.type.toUpperCase()} · {tip.value}
          {tip.relation ? ` · ${tip.relation}` : ""}
        </div>
      )}
    </div>
  );
}
