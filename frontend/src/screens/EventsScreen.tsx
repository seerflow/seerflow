import React, { useState, useCallback } from "react";
import { EventStream } from "@/components/EventStream/EventStream";
import { EventInspector } from "@/components/EventStream/EventInspector";
import { useEventStore } from "@/stores/events";
import type { LiveEvent } from "@/lib/types";

/**
 * Events screen — S-325 redesign.
 * 1fr / 320px grid layout: main event stream on the left,
 * right inspector panel showing details for the selected event.
 */
export const EventsScreen: React.FC = () => {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const events = useEventStore((s) => s.events);

  const selectedEvent: LiveEvent | null =
    selectedId ? (events.find((e) => e.event_id === selectedId) ?? null) : null;

  const handleSelectId = useCallback((id: string | null) => {
    setSelectedId(id);
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
        <EventStream selectedId={selectedId} onSelectId={handleSelectId} />
      </div>

      {/* Right inspector column */}
      <div style={{ overflow: "auto", borderLeft: "1px solid var(--line)" }}>
        <EventInspector event={selectedEvent} />
      </div>
    </div>
  );
};
