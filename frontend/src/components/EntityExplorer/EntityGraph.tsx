import { useEffect, useMemo, useRef, useState } from "react";
import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCenter,
  forceCollide,
} from "d3-force";
import type { EntityRelation } from "@/lib/types";
import { entitySourceColor } from "@/lib/entitySourceColor";

interface FocalNode { uuid: string; label: string; type: string; }

interface Props {
  focal: FocalNode;
  related: EntityRelation[];
  onNavigate: (uuid: string) => void;
}

interface SimNode { id: string; label: string; type: string; x?: number; y?: number; fx?: number | null; fy?: number | null; focal?: boolean; }
interface SimLink { source: string | SimNode; target: string | SimNode; relation: string; }

const MAX_NODES = 100;

export function EntityGraph({ focal, related, onNavigate }: Props) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 400, h: 320 });
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>({});
  const truncated = related.length > MAX_NODES;
  const rendered = useMemo(() => {
    const sorted = [...related];
    return truncated ? sorted.slice(0, MAX_NODES) : sorted;
  }, [related, truncated]);

  useEffect(() => {
    if (!wrapperRef.current) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) setSize({ w: e.contentRect.width, h: Math.max(240, e.contentRect.height) });
    });
    ro.observe(wrapperRef.current);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const nodes: SimNode[] = [
      { id: focal.uuid, label: focal.label, type: focal.type, focal: true },
      ...rendered.map((r) => ({ id: r.entity_uuid, label: r.entity_value, type: r.entity_type })),
    ];
    const links: SimLink[] = rendered.map((r) => ({ source: focal.uuid, target: r.entity_uuid, relation: r.relation_type }));
    const sim = forceSimulation(nodes)
      .force("link", forceLink(links).id((d) => (d as SimNode).id).distance(80))
      .force("charge", forceManyBody().strength(-120))
      .force("center", forceCenter(size.w / 2, size.h / 2))
      .force("collide", forceCollide(18))
      .alpha(1)
      .stop();
    for (let i = 0; i < 300 && sim.alpha() > 0.01; i++) sim.tick();
    const next: Record<string, { x: number; y: number }> = {};
    for (const n of nodes) next[n.id] = { x: n.x ?? size.w / 2, y: n.y ?? size.h / 2 };
    setPositions(next);
  }, [focal.uuid, focal.label, focal.type, rendered, size.w, size.h]);

  const focalPos = positions[focal.uuid] ?? { x: size.w / 2, y: size.h / 2 };

  return (
    <div ref={wrapperRef} className="relative h-80 w-full overflow-hidden rounded-md border">
      {truncated && (
        <div className="absolute left-0 right-0 top-0 z-10 bg-amber-100 px-2 py-1 text-xs text-amber-900 dark:bg-amber-900 dark:text-amber-100">
          Showing top 100 of {related.length} — click a neighbor to explore further.
        </div>
      )}
      <svg
        role="img"
        aria-label={`Relationship graph for ${focal.label} with ${rendered.length} connections`}
        width={size.w}
        height={size.h}
        className="block"
      >
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
        {rendered.map((r) => {
          const p = positions[r.entity_uuid];
          if (!p) return null;
          return (
            <g
              key={r.entity_uuid}
              onClick={() => onNavigate(r.entity_uuid)}
              style={{ cursor: "pointer" }}
            >
              <circle cx={p.x} cy={p.y} r={10} fill={entitySourceColor(`type:${r.entity_type}`)} />
              <text x={p.x} y={p.y + 22} textAnchor="middle" fontSize={10} fill="currentColor">
                {r.entity_value}
              </text>
            </g>
          );
        })}
      </svg>
      {rendered.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground">
          No related entities
        </div>
      )}
    </div>
  );
}
