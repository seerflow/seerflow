import React, { useState, useCallback, useMemo } from "react";
import { EventStream } from "@/components/EventStream/EventStream";
import { EventInspector } from "@/components/EventStream/EventInspector";
import { useEventStore } from "@/stores/events";
import { applyEventQuery, countSeverities } from "@/lib/eventQuery";
import type { LiveEvent } from "@/lib/types";

/**
 * Events screen — S-325 redesign, S-329 query execution, S-331 single field.
 *
 * 1fr / 320px grid layout: main event stream on the left, right inspector
 * panel showing details for the selected event. The screen owns the query
 * state and the derived result (one query language client-side over the
 * loaded events) but the single query field lives in the `EventStream`
 * toolbar — there is no second, screen-level query bar (S-331 consolidation).
 * When a query narrows the set the matched rows render inside the stream and
 * the crit / warn summary recomputes over the filtered set so the counts stay
 * consistent with what is visible.
 */
export const EventsScreen: React.FC = () => {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const events = useEventStore((s) => s.events);

  const result = useMemo(() => applyEventQuery(events, query), [events, query]);
  const matched = result.matched;
  const counts = useMemo(() => countSeverities(matched), [matched]);

  // A query is "active" once it actually narrows the set (mode !== "all").
  const queryActive = result.mode !== "all";

  const selectedEvent: LiveEvent | null =
    selectedId ? (events.find((e) => e.event_id === selectedId) ?? null) : null;

  const handleSelectId = useCallback((id: string | null) => {
    setSelectedId((cur) => (cur === id ? null : id));
  }, []);

  return (
    <div
      data-testid="events-screen"
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 320px",
        height: "100%",
        overflow: "hidden",
      }}
    >
      {/* Main event stream column — single query field lives in its toolbar */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          borderRight: "1px solid var(--line)",
        }}
      >
        <EventStream
          selectedId={selectedId}
          onSelectId={handleSelectId}
          query={query}
          onQueryChange={setQuery}
          matchCount={matched.length}
          critCount={counts.crit}
          warnCount={counts.warn}
          queryValid={result.valid}
          queryHint={result.hint}
          queryActive={queryActive}
          filteredEvents={matched}
        />
      </div>

      {/* Right inspector column */}
      <div style={{ overflow: "auto", borderLeft: "1px solid var(--line)" }}>
        <EventInspector event={selectedEvent} />
      </div>
    </div>
  );
};
