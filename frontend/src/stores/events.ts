import { create } from "zustand";
import type { LiveEvent, EventFilter, WsStatus } from "@/lib/types";

export const MAX_EVENTS = 1000;
export const MAX_PAUSED_BUFFER = 5000;

export interface EventsState {
  events: LiveEvent[];
  pausedBuffer: LiveEvent[];
  paused: boolean;
  filter: EventFilter;
  knownSources: Set<string>;
  status: WsStatus;
  droppedFromRing: number;
  droppedFromPausedBuffer: number;
  lastDisconnectedAtMs: number | null;

  ingest: (events: LiveEvent[]) => void;
  backfill: (events: LiveEvent[]) => void;
  pause: () => void;
  resume: () => void;
  setFilter: (next: Partial<EventFilter>) => void;
  setStatus: (s: WsStatus) => void;
}

const EMPTY_FILTER: EventFilter = {
  sources: new Set(),
  minSeverity: 0,
  templateIds: new Set(),
};

function trackSources(prev: Set<string>, batch: LiveEvent[]): Set<string> {
  let changed = false;
  const next = new Set(prev);
  for (const e of batch) {
    if (!next.has(e.source_type)) {
      next.add(e.source_type);
      changed = true;
    }
  }
  return changed ? next : prev;
}

export const useEventStore = create<EventsState>((set) => ({
  events: [],
  pausedBuffer: [],
  paused: false,
  filter: EMPTY_FILTER,
  knownSources: new Set(),
  status: "connecting",
  droppedFromRing: 0,
  droppedFromPausedBuffer: 0,
  lastDisconnectedAtMs: null,

  ingest: (batch) => set((state) => {
    const knownSources = trackSources(state.knownSources, batch);
    if (state.paused) {
      const merged = [...batch.slice().reverse(), ...state.pausedBuffer];
      const overflow = Math.max(0, merged.length - MAX_PAUSED_BUFFER);
      return {
        pausedBuffer: overflow ? merged.slice(0, MAX_PAUSED_BUFFER) : merged,
        droppedFromPausedBuffer: state.droppedFromPausedBuffer + overflow,
        knownSources,
      };
    }
    const merged = [...batch.slice().reverse(), ...state.events];
    const overflow = Math.max(0, merged.length - MAX_EVENTS);
    return {
      events: overflow ? merged.slice(0, MAX_EVENTS) : merged,
      droppedFromRing: state.droppedFromRing + overflow,
      knownSources,
    };
  }),

  backfill: (batch) => set((state) => {
    const knownSources = trackSources(state.knownSources, batch);
    const merged = [...batch, ...state.events];
    const overflow = Math.max(0, merged.length - MAX_EVENTS);
    return {
      events: overflow ? merged.slice(0, MAX_EVENTS) : merged,
      droppedFromRing: state.droppedFromRing + overflow,
      knownSources,
    };
  }),

  pause: () => set({ paused: true }),

  resume: () => set((state) => {
    const merged = [...state.pausedBuffer, ...state.events];
    const overflow = Math.max(0, merged.length - MAX_EVENTS);
    return {
      events: overflow ? merged.slice(0, MAX_EVENTS) : merged,
      pausedBuffer: [],
      paused: false,
      droppedFromRing: state.droppedFromRing + overflow,
    };
  }),

  setFilter: (next) => set((state) => ({ filter: { ...state.filter, ...next } })),

  setStatus: (status) => set((state) => ({
    status,
    lastDisconnectedAtMs: status === "closed" && state.status !== "closed" ? Date.now() : state.lastDisconnectedAtMs,
  })),
}));

export const selectVisibleEvents = (state: EventsState): LiveEvent[] => {
  const { events, filter } = state;
  if (filter.sources.size === 0 && filter.minSeverity === 0 && filter.templateIds.size === 0) {
    return events;
  }
  return events.filter((e) => {
    if (filter.sources.size && !filter.sources.has(e.source_type)) return false;
    if (e.severity_id < filter.minSeverity) return false;
    if (filter.templateIds.size && !filter.templateIds.has(e.template_id)) return false;
    return true;
  });
};

export const selectPausedCount = (state: EventsState): number => state.pausedBuffer.length;
