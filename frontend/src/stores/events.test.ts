import { beforeEach, describe, expect, it } from "vitest";
import { useEventStore, MAX_EVENTS, MAX_PAUSED_BUFFER, selectVisibleEvents, selectPausedCount } from "./events";
import type { LiveEvent } from "@/lib/types";

function ev(i: number, over: Partial<LiveEvent> = {}): LiveEvent {
  return {
    event_id: `e${i}`,
    timestamp_ns: i,
    observed_ns: i,
    severity_id: 2,
    severity_text: "INFO",
    source_type: "syslog",
    message: `m${i}`,
    template_id: 1,
    entity_refs: [],
    entity_summary: {},
    ...over,
  };
}

beforeEach(() => useEventStore.setState({
  events: [], pausedBuffer: [], paused: false,
  filter: { sources: new Set(), minSeverity: 0, templateIds: new Set() },
  knownSources: new Set(), status: "connecting",
  droppedFromRing: 0, droppedFromPausedBuffer: 0, lastDisconnectedAtMs: null,
}));

describe("eventStore", () => {
  it("ingest prepends newest-first", () => {
    useEventStore.getState().ingest([ev(1), ev(2)]);
    const s = useEventStore.getState().events;
    expect(s.map(e => e.event_id)).toEqual(["e2", "e1"]);
  });

  it("ring evicts oldest at MAX_EVENTS cap", () => {
    const batch = Array.from({ length: MAX_EVENTS + 5 }, (_, i) => ev(i));
    useEventStore.getState().ingest(batch);
    const s = useEventStore.getState();
    expect(s.events.length).toBe(MAX_EVENTS);
    expect(s.droppedFromRing).toBe(5);
  });

  it("paused: ingest routes to pausedBuffer not visible events", () => {
    useEventStore.getState().pause();
    useEventStore.getState().ingest([ev(1)]);
    const s = useEventStore.getState();
    expect(s.events).toEqual([]);
    expect(s.pausedBuffer.map(e => e.event_id)).toEqual(["e1"]);
  });

  it("resume catches up: prepend pausedBuffer, clear flag + buffer", () => {
    useEventStore.getState().ingest([ev(1)]);
    useEventStore.getState().pause();
    useEventStore.getState().ingest([ev(2), ev(3)]);
    useEventStore.getState().resume();
    const s = useEventStore.getState();
    expect(s.paused).toBe(false);
    expect(s.pausedBuffer).toEqual([]);
    expect(s.events.map(e => e.event_id)).toEqual(["e3", "e2", "e1"]);
  });

  it("paused buffer caps at MAX_PAUSED_BUFFER, oldest evicted", () => {
    useEventStore.getState().pause();
    const batch = Array.from({ length: MAX_PAUSED_BUFFER + 3 }, (_, i) => ev(i));
    useEventStore.getState().ingest(batch);
    const s = useEventStore.getState();
    expect(s.pausedBuffer.length).toBe(MAX_PAUSED_BUFFER);
    expect(s.droppedFromPausedBuffer).toBe(3);
  });

  it("backfill bypasses paused", () => {
    useEventStore.getState().pause();
    useEventStore.getState().backfill([ev(1), ev(2)]);
    const s = useEventStore.getState();
    expect(s.events.length).toBe(2);
    expect(s.pausedBuffer.length).toBe(0);
  });

  it("ingest tracks distinct knownSources", () => {
    useEventStore.getState().ingest([ev(1, { source_type: "auth" }), ev(2, { source_type: "syslog" }), ev(3, { source_type: "auth" })]);
    expect([...useEventStore.getState().knownSources].sort()).toEqual(["auth", "syslog"]);
  });

  it("setFilter merges partials", () => {
    useEventStore.getState().setFilter({ minSeverity: 4 });
    expect(useEventStore.getState().filter.minSeverity).toBe(4);
    useEventStore.getState().setFilter({ sources: new Set(["auth"]) });
    const f = useEventStore.getState().filter;
    expect(f.minSeverity).toBe(4);
    expect([...f.sources]).toEqual(["auth"]);
  });

  it("selectVisibleEvents filters by source / severity / template", () => {
    useEventStore.getState().ingest([
      ev(1, { source_type: "auth", severity_id: 2, template_id: 10 }),
      ev(2, { source_type: "syslog", severity_id: 5, template_id: 10 }),
      ev(3, { source_type: "auth", severity_id: 5, template_id: 20 }),
    ]);
    useEventStore.getState().setFilter({
      sources: new Set(["auth"]),
      minSeverity: 4,
      templateIds: new Set([10]),
    });
    const v = selectVisibleEvents(useEventStore.getState());
    expect(v).toEqual([]);  // no event matches all 3
    useEventStore.getState().setFilter({ templateIds: new Set([20]) });
    const v2 = selectVisibleEvents(useEventStore.getState());
    expect(v2.map(e => e.event_id)).toEqual(["e3"]);
  });

  it("selectPausedCount returns pausedBuffer length", () => {
    useEventStore.getState().pause();
    useEventStore.getState().ingest([ev(1), ev(2)]);
    expect(selectPausedCount(useEventStore.getState())).toBe(2);
  });
});
