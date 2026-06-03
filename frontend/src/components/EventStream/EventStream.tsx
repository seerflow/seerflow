import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useEventStore, selectPausedCount } from "@/stores/events";
import { EventRow } from "./EventRow";
import { PauseControl } from "./PauseControl";
import { EventTableHeader } from "./EventTableHeader";
import { MiniVolumeStrip } from "./MiniVolumeStrip";
import { api, ApiError } from "@/lib/api";
import { logger } from "@/lib/logger";
import { LiveEventSchema } from "@/lib/schemas";
import { createFilterSlot } from "@/lib/wsFilter";
import * as wsBus from "@/lib/wsBus";
import { useWsSend } from "@/components/WsProvider";
import { useDebouncedWsSend } from "@/hooks/useDebouncedWsSend";
import { useStreamingSeries } from "@/viz/useStreamingSeries";
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

interface Props {
  /** Controlled selected event ID — from parent EventsScreen (optional). */
  selectedId?: string | null;
  /** Callback when user selects/deselects a row (optional). */
  onSelectId?: (id: string | null) => void;
  /**
   * Controlled query value (S-331). When `onQueryChange` is supplied the
   * toolbar field is driven by the parent (single source of truth); otherwise
   * the field keeps its own local state (standalone / legacy behavior).
   */
  query?: string;
  /** Callback when the toolbar query field changes (S-331, controlled mode). */
  onQueryChange?: (q: string) => void;
  /** Number of events matching the active query — shown in the toolbar. */
  matchCount?: number;
  /** Crit count over the matched set (parent-supplied, controlled mode). */
  critCount?: number;
  /** Warn count over the matched set (parent-supplied, controlled mode). */
  warnCount?: number;
  /** Whether the active query parsed/validated cleanly. */
  queryValid?: boolean;
  /** Non-blocking validity hint to show when `queryValid` is false. */
  queryHint?: string;
  /** True once the query narrows the set — render `filteredEvents` not live. */
  queryActive?: boolean;
  /** The matched subset to render when `queryActive` (controlled mode). */
  filteredEvents?: LiveEvent[];
}

export function EventStream({
  selectedId,
  onSelectId,
  query: queryProp,
  onQueryChange,
  matchCount,
  critCount: critProp,
  warnCount: warnProp,
  queryValid = true,
  queryHint,
  queryActive = false,
  filteredEvents,
}: Props = {}): JSX.Element {
  const filter = useEventStore((s) => s.filter);
  const paused = useEventStore((s) => s.paused);
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
  const { backfill, pause, resume } = useEventStore.getState();
  // Uncontrolled expanded ID for rows not wired to parent inspector
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [virtualizerReady, setVirtualizerReady] = useState(false);
  const [status, setStatus] = useState<WsStatus>("connecting");
  const send = useWsSend();

  // Volume ring buffer — 60 seconds at 1s resolution
  const volSeries = useStreamingSeries<[number, number, number]>({ capacity: 60 });
  // Per-second bucket counters (reset each second)
  const bucketRef = useRef({ total: 0, crit: 0, warn: 0 });
  const [critCount, setCritCount] = useState(0);
  const [warnCount, setWarnCount] = useState(0);

  // wsBus subscriptions
  useEffect(() => {
    const offs = [
      wsBus.on("event", (m) => {
        useEventStore.getState().ingest([m.data]);
        // Count into current bucket
        bucketRef.current.total++;
        if (m.data.severity_id >= 6) bucketRef.current.crit++;
        else if (m.data.severity_id >= 4) bucketRef.current.warn++;
      }),
      wsBus.on("batch", (m) => {
        const first = m.events[0];
        if (isLiveEvent(first)) {
          useEventStore.getState().ingest(m.events);
          for (const e of m.events) {
            bucketRef.current.total++;
            if (e.severity_id >= 6) bucketRef.current.crit++;
            else if (e.severity_id >= 4) bucketRef.current.warn++;
          }
        }
      }),
      wsBus.on("__status", (m) => setStatus(m.status)),
    ];
    return () => { for (const off of offs) off(); };
  }, []);

  // 1-second interval to flush the bucket into the ring buffer
  useEffect(() => {
    const id = setInterval(() => {
      const { total, crit, warn } = bucketRef.current;
      bucketRef.current = { total: 0, crit: 0, warn: 0 };
      volSeries.push(Date.now() / 1000, [total, crit, warn]);
      setCritCount((prev) => prev + crit);
      setWarnCount((prev) => prev + warn);
    }, 1000);
    return () => clearInterval(id);
  }, [volSeries]);

  // REST warm-up
  useEffect(() => {
    let cancelled = false;
    api.get<{ items: LiveEvent[] }>("/api/v1/events?limit=100", { schema: LiveEventSchema, itemsKey: "items" })
      .then((r) => { if (!cancelled) backfill(r.items); })
      .catch((e: ApiError) => logger.warn("event warm-up failed", e));
    return () => { cancelled = true; };
  }, [backfill]);

  // Push WS filter intent on filter change (debounce 150 ms)
  const debouncedSend = useDebouncedWsSend(send, 150);
  useEffect(() => {
    const merged = eventsSlot.set(intentFromFilter(filter));
    debouncedSend(merged);
  }, [filter, debouncedSend]);

  useEffect(() => () => {
    eventsSlot.clear();
  }, []);

  // Virtualizer
  const parentRef = useRef<HTMLDivElement>(null);

  // Effective selected ID: controlled when parent passes selectedId, else use internal expandedId
  const effectiveSelectedId = selectedId !== undefined ? selectedId : expandedId;

  const estimateSize = useCallback(
    (i: number): number => (visible[i]?.event_id === effectiveSelectedId ? 220 : 28),
    [visible, effectiveSelectedId],
  );
  const rv = useVirtualizer({
    count: visible.length,
    getScrollElement: () => parentRef.current,
    estimateSize,
    overscan: 8,
  });

  useEffect(() => {
    if (parentRef.current && parentRef.current.clientHeight > 0) {
      setVirtualizerReady(true);
    }
  }, [visible.length]);

  useEffect(() => { rv.measure(); }, [effectiveSelectedId, rv]);

  const togglePause = useCallback((): void => {
    if (paused) resume(); else pause();
  }, [paused, pause, resume]);

  const toggleRow = useCallback((id: string): void => {
    if (onSelectId) {
      // Controlled mode: toggle via parent callback
      const next = effectiveSelectedId === id ? null : id;
      onSelectId(next);
    } else {
      // Uncontrolled mode
      setExpandedId((cur) => (cur === id ? null : id));
    }
  }, [onSelectId, effectiveSelectedId]);

  const virtualItems = rv.getVirtualItems();
  const useFallback = !virtualizerReady || virtualItems.length === 0;

  // Toolbar query field. Controlled by the parent (single source of truth, S-331)
  // when `onQueryChange` is supplied; otherwise locally stateful (standalone).
  const controlled = onQueryChange !== undefined;
  const [localQuery, setLocalQuery] = useState("");
  const query = controlled ? (queryProp ?? "") : localQuery;
  const handleQueryChange = useCallback(
    (value: string): void => {
      if (onQueryChange) onQueryChange(value);
      else setLocalQuery(value);
    },
    [onQueryChange],
  );

  // Crit / warn shown in the toolbar: parent-supplied (matched set) when
  // controlled, else the live-derived running counters.
  const shownCrit = controlled && critProp !== undefined ? critProp : critCount;
  const shownWarn = controlled && warnProp !== undefined ? warnProp : warnCount;

  const volArrays = volSeries.data;
  const volTimestamps = volArrays.timestamps;
  const volValues = volArrays.values[0] ?? [];

  return (
    // S-335: flush full-bleed flex column — the column chrome (borderRight,
    // overflow) is supplied by EventsScreen; no card wrapper here.
    <section className="flex flex-col h-full min-h-0 overflow-hidden">
      {/* Toolbar */}
      <header
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "11px 24px",
          borderBottom: "1px solid var(--line)",
          flexShrink: 0,
        }}
      >
        {/* Live dot + label */}
        <div
          data-testid="live-label"
          style={{ display: "flex", alignItems: "center", gap: 6 }}
        >
          <span
            aria-label={`WebSocket status: ${status}`}
            style={{
              display: "inline-block",
              width: 8,
              height: 8,
              borderRadius: "50%",
              background:
                status === "open"
                  ? "var(--accent)"
                  : status === "connecting"
                  ? "var(--warn)"
                  : "var(--crit)",
              animation: status === "open" ? "pulse 2s infinite" : undefined,
            }}
          />
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              color: "var(--text-3)",
              textTransform: "uppercase",
              letterSpacing: "0.1em",
            }}
          >
            live
          </span>
        </div>

        {/* Query field — single source of truth (S-331) */}
        <div
          data-testid="query-field"
          style={{
            display: "flex",
            alignItems: "center",
            flex: 1,
            gap: 8,
            border: `1px solid ${queryValid ? "var(--line)" : "var(--warn)"}`,
            borderRadius: 4,
            padding: "4px 10px",
            background: "var(--surface-2)",
          }}
        >
          <input
            data-testid="event-query-field"
            type="text"
            placeholder="query events… (jq · sigma · sql)"
            value={query}
            onChange={(e) => handleQueryChange(e.target.value)}
            style={{
              flex: 1,
              background: "transparent",
              border: "none",
              outline: "none",
              fontFamily: "var(--font-mono)",
              fontSize: 12,
              color: "var(--text)",
            }}
          />
          {matchCount !== undefined && (
            <span
              data-testid="event-match-count"
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 10,
                color: "var(--text-3)",
                whiteSpace: "nowrap",
              }}
            >
              {matchCount} matched
            </span>
          )}
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              color: "var(--text-3)",
              whiteSpace: "nowrap",
            }}
          >
            jq · sigma · sql
          </span>
        </div>

        {/* Crit / warn summary over the visible (matched) set */}
        <span style={{ display: "flex", gap: 12, fontFamily: "var(--font-mono)", fontSize: 11 }}>
          <span data-testid="events-crit-count" style={{ color: "var(--crit)" }}>
            {shownCrit} crit
          </span>
          <span data-testid="events-warn-count" style={{ color: "var(--warn)" }}>
            {shownWarn} warn
          </span>
        </span>

        {/* Pause */}
        <PauseControl paused={paused} bufferedCount={bufferedCount} onToggle={togglePause} />

        {/* Export */}
        <button
          aria-label="Export events"
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: "var(--text-2)",
            background: "transparent",
            border: "1px solid var(--line)",
            borderRadius: 4,
            padding: "4px 10px",
            cursor: "pointer",
          }}
        >
          Export
        </button>
      </header>

      {/* Non-blocking validity hint for an invalid query (S-331) */}
      {!queryValid && queryHint && (
        <div
          style={{
            padding: "4px 24px",
            borderBottom: "1px solid var(--line)",
            flexShrink: 0,
          }}
        >
          <span
            data-testid="query-hint"
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              color: "var(--warn)",
            }}
          >
            {queryHint} — showing all events
          </span>
        </div>
      )}

      {/* MiniVolume strip */}
      <MiniVolumeStrip
        timestamps={volTimestamps}
        values={volValues}
        critCount={critCount}
        warnCount={warnCount}
      />

      {/* Table header */}
      <EventTableHeader />

      {/* When a query narrows the set (S-331) render the matched subset; the
          live virtualized stream is reserved for the unfiltered view. */}
      {queryActive ? (
        <div className="flex-1 overflow-y-auto" data-testid="matched-results">
          {(filteredEvents ?? []).length === 0 ? (
            <div className="p-6 text-center text-xs text-muted-foreground">
              No events match the current query.
            </div>
          ) : (
            (filteredEvents ?? []).map((e) => (
              <EventRow
                key={e.event_id}
                event={e}
                expanded={effectiveSelectedId === e.event_id}
                onToggle={toggleRow}
              />
            ))
          )}
        </div>
      ) : (
      /* Event list */
      <div ref={parentRef} className="flex-1 overflow-y-auto">
        {visible.length === 0 ? (
          <div className="p-6 text-center text-xs text-muted-foreground">No events yet — waiting for the pipeline to send some.</div>
        ) : useFallback ? (
          <div>
            {visible.slice(0, MAX_FALLBACK_ROWS).map((e) => (
              <EventRow
                key={e.event_id}
                event={e}
                expanded={effectiveSelectedId === e.event_id}
                onToggle={toggleRow}
              />
            ))}
          </div>
        ) : (
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
                  <EventRow
                    event={e}
                    expanded={effectiveSelectedId === e.event_id}
                    onToggle={toggleRow}
                  />
                </div>
              );
            })}
          </div>
          /* v8 ignore stop */
        )}
      </div>
      )}
    </section>
  );
}

const MAX_FALLBACK_ROWS = 50;
