import React, { useState, useCallback, useMemo } from "react";
import { EventStream } from "@/components/EventStream/EventStream";
import { EventInspector } from "@/components/EventStream/EventInspector";
import { EventRow } from "@/components/EventStream/EventRow";
import { useEventStore } from "@/stores/events";
import { applyEventQuery, countSeverities } from "@/lib/eventQuery";
import type { LiveEvent } from "@/lib/types";

/**
 * Events screen — S-325 redesign, S-329 query execution.
 *
 * 1fr / 320px grid layout: main event stream on the left, right inspector
 * panel showing details for the selected event. A screen-level query bar
 * (S-329) runs the jq / sigma / sql query language client-side over the
 * loaded events; when a query narrows the set the matched rows render in a
 * results region and the crit / warn summary recomputes over the filtered
 * set so the counts stay consistent with what is visible.
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
      {/* Main event stream column */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          borderRight: "1px solid var(--line)",
        }}
      >
        {/* S-329 query bar + crit/warn summary */}
        <QueryBar
          query={query}
          onQueryChange={setQuery}
          matchCount={matched.length}
          critCount={counts.crit}
          warnCount={counts.warn}
          valid={result.valid}
          hint={result.hint}
        />

        {queryActive ? (
          <MatchedResults
            matched={matched}
            selectedId={selectedId}
            onSelect={handleSelectId}
          />
        ) : (
          <EventStream selectedId={selectedId} onSelectId={handleSelectId} />
        )}
      </div>

      {/* Right inspector column */}
      <div style={{ overflow: "auto", borderLeft: "1px solid var(--line)" }}>
        <EventInspector event={selectedEvent} />
      </div>
    </div>
  );
};

interface QueryBarProps {
  query: string;
  onQueryChange: (q: string) => void;
  matchCount: number;
  critCount: number;
  warnCount: number;
  valid: boolean;
  hint?: string;
}

const QueryBar: React.FC<QueryBarProps> = ({
  query,
  onQueryChange,
  matchCount,
  critCount,
  warnCount,
  valid,
  hint,
}) => (
  <div
    style={{
      display: "flex",
      flexDirection: "column",
      gap: 4,
      padding: "8px 24px",
      borderBottom: "1px solid var(--line)",
      flexShrink: 0,
    }}
  >
    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          flex: 1,
          gap: 8,
          border: `1px solid ${valid ? "var(--line)" : "var(--warn)"}`,
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
          onChange={(e) => onQueryChange(e.target.value)}
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
      </div>

      <span style={{ display: "flex", gap: 12, fontFamily: "var(--font-mono)", fontSize: 11 }}>
        <span data-testid="events-crit-count" style={{ color: "var(--crit)" }}>
          {critCount} crit
        </span>
        <span data-testid="events-warn-count" style={{ color: "var(--warn)" }}>
          {warnCount} warn
        </span>
      </span>
    </div>

    {!valid && hint && (
      <span
        data-testid="query-hint"
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          color: "var(--warn)",
        }}
      >
        {hint} — showing all events
      </span>
    )}
  </div>
);

interface MatchedResultsProps {
  matched: LiveEvent[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}

const MatchedResults: React.FC<MatchedResultsProps> = ({ matched, selectedId, onSelect }) => (
  <div className="flex-1 overflow-y-auto" data-testid="matched-results">
    {matched.length === 0 ? (
      <div className="p-6 text-center text-xs text-muted-foreground">
        No events match the current query.
      </div>
    ) : (
      matched.map((e) => (
        <EventRow
          key={e.event_id}
          event={e}
          expanded={selectedId === e.event_id}
          onToggle={(id) => onSelect(id)}
        />
      ))
    )}
  </div>
);
