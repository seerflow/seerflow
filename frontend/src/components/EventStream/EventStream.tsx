import { useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useEventStore, selectVisibleEvents, selectPausedCount } from "@/stores/events";
import { EventRow } from "./EventRow";
import { PauseControl } from "./PauseControl";
import { EventFilterBar } from "./EventFilterBar";
import { api, ApiError } from "@/lib/api";
import { logger } from "@/lib/logger";
import { setIntent as setWsIntent } from "@/lib/wsFilter";
import type { LiveEvent, EventFilter } from "@/lib/types";

function intentFromFilter(f: EventFilter): Parameters<typeof setWsIntent>[1] {
  return {
    sources: f.sources.size ? [...f.sources] : undefined,
    template_ids: f.templateIds.size ? [...f.templateIds] : undefined,
    min_severity: f.minSeverity > 0 ? f.minSeverity : undefined,
  };
}

export function EventStream(): JSX.Element {
  const filter = useEventStore((s) => s.filter);
  const paused = useEventStore((s) => s.paused);
  const status = useEventStore((s) => s.status);
  const knownSources = useEventStore((s) => s.knownSources);
  const visible = useEventStore(selectVisibleEvents);
  const bufferedCount = useEventStore(selectPausedCount);
  const { backfill, pause, resume, setFilter } = useEventStore.getState();
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [showDisconnected, setShowDisconnected] = useState(false);

  // REST warm-up
  useEffect(() => {
    let cancelled = false;
    api.get<{ items: LiveEvent[] }>("/api/v1/events?limit=100")
      .then((r) => { if (!cancelled) backfill(r.items); })
      .catch((e: ApiError) => logger.warn("event warm-up failed", e));
    return () => { cancelled = true; };
  }, [backfill]);

  // Push WS filter intent on filter change (debounce 150 ms)
  useEffect(() => {
    const t = setTimeout(() => {
      setWsIntent("events", intentFromFilter(filter));
      window.dispatchEvent(new CustomEvent("seerflow:wsfilter-changed"));
    }, 150);
    return () => clearTimeout(t);
  }, [filter]);

  // Disconnected banner after 3 s
  useEffect(() => {
    if (status === "closed") {
      const t = setTimeout(() => setShowDisconnected(true), 3000);
      return () => clearTimeout(t);
    }
    setShowDisconnected(false);
    return undefined;
  }, [status]);

  // Virtualizer
  const parentRef = useRef<HTMLDivElement>(null);
  const rv = useVirtualizer({
    count: visible.length,
    getScrollElement: () => parentRef.current,
    estimateSize: (i) => (visible[i]?.event_id === expandedId ? 220 : 28),
    overscan: 8,
  });

  const knownSourcesList = useMemo(
    () => [...knownSources].sort().slice(0, 50),
    [knownSources],
  );

  const togglePause = (): void => {
    if (paused) resume(); else pause();
  };

  const toggleRow = (id: string): void => {
    setExpandedId((cur) => (cur === id ? null : id));
    rv.measure();
  };

  return (
    <section className="flex flex-col h-[420px] rounded border bg-card">
      <header className="flex items-center justify-between gap-2 border-b px-3 py-2">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold">Live Event Stream</h2>
          <span
            aria-label={`status ${status}`}
            className={`inline-block h-2 w-2 rounded-full ${status === "open" ? "bg-emerald-500" : status === "connecting" ? "bg-amber-500" : "bg-red-500"}`}
          />
        </div>
        <PauseControl paused={paused} bufferedCount={bufferedCount} onToggle={togglePause} />
      </header>
      <EventFilterBar filter={filter} knownSources={knownSourcesList} onChange={setFilter} />
      {showDisconnected && (
        <div role="status" aria-live="polite" className="bg-amber-500/10 px-3 py-1 text-xs text-amber-700">
          Live stream disconnected — retrying…
        </div>
      )}
      <div ref={parentRef} className="flex-1 overflow-y-auto">
        {visible.length === 0 ? (
          <div className="p-6 text-center text-xs text-muted-foreground">No events yet — waiting for the pipeline to send some.</div>
        ) : rv.getVirtualItems().length === 0 ? (
          // Virtualizer has not measured yet (or running in jsdom with no layout).
          // Render plain list so rows are reachable for a11y + tests.
          <div>
            {visible.map((e) => (
              <EventRow key={e.event_id} event={e} expanded={expandedId === e.event_id} onToggle={toggleRow} />
            ))}
          </div>
        ) : (
          <div style={{ height: rv.getTotalSize(), position: "relative" }}>
            {rv.getVirtualItems().map((vi) => {
              const e = visible[vi.index];
              return (
                <div
                  key={e.event_id}
                  style={{ position: "absolute", top: 0, left: 0, width: "100%", transform: `translateY(${vi.start}px)` }}
                  ref={rv.measureElement}
                  data-index={vi.index}
                >
                  <EventRow event={e} expanded={expandedId === e.event_id} onToggle={toggleRow} />
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
