import { useMemo, useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { entitySourceColor } from "@/lib/entitySourceColor";
import type { EntityEvent } from "@/lib/types";

interface Props {
  events: EntityEvent[];
  total: number;
  limit: number;
}

function dayKey(ns: bigint): string {
  return new Date(Number(ns / 1_000_000n)).toLocaleDateString();
}

function formatTime(ns: bigint): string {
  return new Date(Number(ns / 1_000_000n)).toLocaleTimeString(undefined, { hour12: false });
}

interface Row { type: "header" | "event"; key: string; date?: string; event?: EntityEvent; }

function toRows(events: EntityEvent[]): Row[] {
  const rows: Row[] = [];
  let lastDay = "";
  for (const e of events) {
    const d = dayKey(e.timestamp_ns);
    if (d !== lastDay) {
      rows.push({ type: "header", key: `h-${d}`, date: d });
      lastDay = d;
    }
    rows.push({ type: "event", key: e.event_id, event: e });
  }
  return rows;
}

export function EntityTimelineList({ events, total, limit }: Props) {
  const parentRef = useRef<HTMLDivElement>(null);
  const rows = useMemo(() => toRows(events), [events]);
  const virtualize = rows.length > 200;
  const virt = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 32,
    overscan: 10,
    enabled: virtualize,
  });

  if (events.length === 0) {
    return <div className="p-6 text-center text-sm text-muted-foreground">No events for this entity in the selected range.</div>;
  }

  const renderRow = (row: Row) => row.type === "header" ? (
    <div key={row.key} className="sticky top-0 z-10 bg-background/95 px-2 py-1 text-xs font-semibold uppercase text-muted-foreground border-b">
      {row.date}
    </div>
  ) : (
    <div key={row.key} className="flex items-center gap-2 px-2 py-1.5 text-sm border-b">
      <span className="font-mono text-xs text-muted-foreground">{formatTime(row.event!.timestamp_ns)}</span>
      {row.event!.ioc_matches && row.event!.ioc_matches.length > 0 ? (
        <span
          className="rounded bg-purple-700 px-1.5 py-0.5 text-[10px] font-semibold text-white"
          title={row.event!.ioc_matches
            .map((m) => `${m.type}:${m.value} (${m.source_feed}, conf=${m.confidence})`)
            .join("\n")}
        >
          TI
        </span>
      ) : null}
      <span
        className="rounded px-1.5 py-0.5 text-[10px] font-semibold text-white"
        style={{ backgroundColor: entitySourceColor(row.event!.source_type) }}
      >
        {row.event!.source_type}
      </span>
      <span className="rounded border px-1.5 py-0.5 text-[10px]">sev {row.event!.severity_id}</span>
      <span className="flex-1 truncate">{row.event!.message}</span>
    </div>
  );

  return (
    <div className="flex flex-col h-full">
      <div ref={parentRef} className="flex-1 overflow-auto" style={{ contain: "strict" }}>
        {virtualize ? (
          <div style={{ height: `${virt.getTotalSize()}px`, position: "relative" }}>
            {virt.getVirtualItems().map((vi) => (
              <div
                key={rows[vi.index].key}
                style={{ position: "absolute", top: 0, left: 0, right: 0, transform: `translateY(${vi.start}px)` }}
              >
                {renderRow(rows[vi.index])}
              </div>
            ))}
          </div>
        ) : rows.map(renderRow)}
      </div>
      {total === limit && (
        <div className="border-t bg-amber-100 p-2 text-xs text-amber-900 dark:bg-amber-900 dark:text-amber-100">
          Timeline may be truncated — narrow the range or raise the limit.
        </div>
      )}
    </div>
  );
}
