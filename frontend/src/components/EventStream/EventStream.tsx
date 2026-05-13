import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useEventStore, selectPausedCount } from "@/stores/events";
import { EventRow } from "./EventRow";
import { PauseControl } from "./PauseControl";
import { EventFilterBar } from "./EventFilterBar";
import { api, ApiError } from "@/lib/api";
import { logger } from "@/lib/logger";
import { LiveEventSchema } from "@/lib/schemas";
import { createFilterSlot } from "@/lib/wsFilter";
import * as wsBus from "@/lib/wsBus";
import { useWsSend } from "@/components/WsProvider";
import { useDebouncedWsSend } from "@/hooks/useDebouncedWsSend";
import type { LiveEvent, EventFilter, WsStatus } from "@/lib/types";
import { isLiveEvent } from "@/lib/types";

// One-shot WsFilter capability for this widget — the module is imported once
// per worker so `createFilterSlot("events")` fires exactly once. Test harnesses
// call `_resetForTests()` which clears the issued set without breaking this
// already-bound closure.
const eventsSlot = createFilterSlot("events");

function intentFromFilter(f: EventFilter): Parameters<typeof eventsSlot.set>[0] {
  return {
    sources: f.sources.size ? [...f.sources] : undefined,
    template_ids: f.templateIds.size ? [...f.templateIds] : undefined,
    min_severity: f.minSeverity > 0 ? f.minSeverity : undefined,
  };
}

export function EventStream(): JSX.Element {
  const filter = useEventStore((s) => s.filter);
  const paused = useEventStore((s) => s.paused);
  const knownSources = useEventStore((s) => s.knownSources);
  // Subscribe to raw events ref + filter; memoize the filtered slice locally so
  // unrelated store updates (paused, dropped counters) don't cascade into a
  // re-filter of the entire ring buffer.
  const events = useEventStore((s) => s.events);
  const visible = useMemo<LiveEvent[]>(() => {
    if (filter.sources.size === 0 && filter.minSeverity === 0 && filter.templateIds.size === 0) {
      return events;
    }
    return events.filter((e) => {
      if (filter.sources.size && !filter.sources.has(e.source_type)) return false;
      if (e.severity_id < filter.minSeverity) return false;
      if (filter.templateIds.size && !filter.templateIds.has(e.template_id)) return false;
      return true;
    });
  }, [events, filter]);
  const bufferedCount = useEventStore(selectPausedCount);
  const { backfill, pause, resume, setFilter } = useEventStore.getState();
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [virtualizerReady, setVirtualizerReady] = useState(false);
  const [status, setStatus] = useState<WsStatus>("connecting");
  const send = useWsSend();

  // wsBus subscriptions (S-062 Phase A): EventStream is the sole ingestor of
  // LiveEvent frames into useEventStore. AlertFeed used to fan-out here as a
  // transitional double-write; that path has been removed in this task to
  // prevent duplicate rows.
  useEffect(() => {
    const offs = [
      wsBus.on("event", (m) => {
        // m.data was pre-validated + bigint-converted by useWebSocket.
        useEventStore.getState().ingest([m.data]);
      }),
      wsBus.on("batch", (m) => {
        // Heterogeneous envelope — only ingest LiveEvent-shaped batches.
        // S-208: isLiveEvent replaces the `"event_id" in first` stringly-typed check.
        const first = m.events[0];
        if (isLiveEvent(first)) {
          useEventStore.getState().ingest(m.events);
        }
      }),
      wsBus.on("__status", (m) => setStatus(m.status)),
    ];
    return () => { for (const off of offs) off(); };
  }, []);

  // REST warm-up
  useEffect(() => {
    let cancelled = false;
    api.get<{ items: LiveEvent[] }>("/api/v1/events?limit=100", { schema: LiveEventSchema, itemsKey: "items" })
      .then((r) => { if (!cancelled) backfill(r.items); })
      .catch((e: ApiError) => logger.warn("event warm-up failed", e));
    return () => { cancelled = true; };
  }, [backfill]);

  // Push WS filter intent on filter change (debounce 150 ms). S-208: shared
  // hook. Clear on unmount stays in the separate effect below.
  const debouncedSend = useDebouncedWsSend(send, 150);
  useEffect(() => {
    const merged = eventsSlot.set(intentFromFilter(filter));
    debouncedSend(merged);
  }, [filter, debouncedSend]);

  useEffect(() => () => {
    eventsSlot.clear();
    // No CustomEvent dispatch — AlertFeed no longer listens for the legacy
    // "seerflow:wsfilter-changed" hop; filter merging happens via useWsSend().
  }, []);

  // Virtualizer — keep estimateSize closure fresh by re-creating it whenever
  // expandedId changes. useVirtualizer rebinds internally on instance change.
  const parentRef = useRef<HTMLDivElement>(null);
  const estimateSize = useCallback(
    (i: number): number => (visible[i]?.event_id === expandedId ? 220 : 28),
    [visible, expandedId],
  );
  const rv = useVirtualizer({
    count: visible.length,
    getScrollElement: () => parentRef.current,
    estimateSize,
    overscan: 8,
  });

  // Once parent is measured, virtualizer becomes the source of truth. Until
  // then we render an empty placeholder rather than dumping the full list.
  useEffect(() => {
    if (parentRef.current && parentRef.current.clientHeight > 0) {
      setVirtualizerReady(true);
    }
  }, [visible.length]);

  // Re-measure on row expansion in a layout effect so estimateSize sees the new
  // expandedId before the virtualizer reads it.
  useEffect(() => { rv.measure(); }, [expandedId, rv]);

  const knownSourcesList = useMemo(
    () => [...knownSources].sort().slice(0, 50),
    [knownSources],
  );

  const togglePause = useCallback((): void => {
    if (paused) resume(); else pause();
  }, [paused, pause, resume]);

  const toggleRow = useCallback((id: string): void => {
    setExpandedId((cur) => (cur === id ? null : id));
  }, []);

  // True when @tanstack/react-virtual has produced items. In jsdom (no layout)
  // and on the very first paint in production this is empty; we then fall back
  // to a plain list. The virtualizerReady flag stops the fallback from running
  // in production once the parent has measured even a single time.
  const virtualItems = rv.getVirtualItems();
  const useFallback = !virtualizerReady || virtualItems.length === 0;

  return (
    <section className="flex flex-col h-full min-h-0 rounded border bg-card">
      <header className="flex items-center justify-between gap-2 border-b px-3 py-2">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold">Live Event Stream</h2>
          <span
            aria-label={`WebSocket status: ${status}`}
            className={`inline-block h-2 w-2 rounded-full ${status === "open" ? "bg-emerald-500" : status === "connecting" ? "bg-amber-500" : "bg-red-500"}`}
          />
        </div>
        <PauseControl paused={paused} bufferedCount={bufferedCount} onToggle={togglePause} />
      </header>
      <EventFilterBar filter={filter} knownSources={knownSourcesList} onChange={setFilter} />
      {/* Disconnected banner now lives at the dashboard header via <DisconnectedBanner />. */}
      <div ref={parentRef} className="flex-1 overflow-y-auto">
        {visible.length === 0 ? (
          <div className="p-6 text-center text-xs text-muted-foreground">No events yet — waiting for the pipeline to send some.</div>
        ) : useFallback ? (
          // Pre-measurement (or jsdom). Render the first MAX_FALLBACK rows so
          // tests + a11y work and we don't dump 1000 unvirtualized rows on first
          // paint. The virtualizer takes over the moment parent dimensions land.
          <div>
            {visible.slice(0, MAX_FALLBACK_ROWS).map((e) => (
              <EventRow key={e.event_id} event={e} expanded={expandedId === e.event_id} onToggle={toggleRow} />
            ))}
          </div>
        ) : (
          // jsdom has no layout engine, so @tanstack/react-virtual never
          // produces items in unit tests — useFallback stays true and this
          // branch is unreachable. Covered by Playwright E2E in a real browser.
          /* v8 ignore start */
          <div style={{ height: rv.getTotalSize(), position: "relative" }}>
            {virtualItems.map((vi) => {
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
          /* v8 ignore stop */
        )}
      </div>
    </section>
  );
}

const MAX_FALLBACK_ROWS = 50;
