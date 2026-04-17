import { create, type StoreApi, type UseBoundStore } from "zustand";

import {
  bucketStartNs,
  defaultResolution,
  RESOLUTION_NS,
} from "@/lib/buckets";
import type {
  AnomalyEvent,
  TimelineBucket,
  TimelineRange,
  TimelineResolution,
} from "@/lib/types";

export interface AnomalyState {
  range: TimelineRange;
  resolution: TimelineResolution;
  source: string | null;
  items: TimelineBucket[];
  loading: boolean;
  error: string | null;

  knownSources: Set<string>;
  alertCountTruncated: boolean;

  setRange: (r: TimelineRange) => void;
  setResolution: (r: TimelineResolution) => void;
  setSource: (s: string | null) => void;
  replaceSeries: (items: TimelineBucket[]) => void;
  appendScore: (e: AnomalyEvent) => void;
  rolloverIfStale: (nowNs: number) => void;
  setLoading: (b: boolean) => void;
  setError: (s: string | null) => void;
  setAlertCountTruncated: (b: boolean) => void;
}

const MAX_ITEMS = 2016;

function bucketIndexFor(ts_ns: number, resolution: TimelineResolution): number {
  return Number(bucketStartNs(BigInt(ts_ns), resolution));
}

const INITIAL_STATE = {
  range: "1h" as TimelineRange,
  resolution: "1m" as TimelineResolution,
  source: null as string | null,
  items: [] as TimelineBucket[],
  loading: false,
  error: null as string | null,
  knownSources: new Set<string>() as Set<string>,
  alertCountTruncated: false,
};

export function createAnomalyStore(): UseBoundStore<StoreApi<AnomalyState>> {
  return create<AnomalyState>((set, get) => ({
    ...INITIAL_STATE,

    setRange: (r) => set({ range: r, resolution: defaultResolution(r) }),
    setResolution: (r) => set({ resolution: r }),
    setSource: (s) => set({ source: s }),
    replaceSeries: (items) => set({ items: items.slice(-MAX_ITEMS) }),
    setLoading: (b) => set({ loading: b }),
    setError: (s) => set({ error: s }),
    setAlertCountTruncated: (b) => set({ alertCountTruncated: b }),

    appendScore: (e) => {
      const state = get();
      // Always track the source so the widget can offer it as a filter option,
      // even when the event is filtered out by the current source selection.
      if (!state.knownSources.has(e.source_type)) {
        const nextSources = new Set(state.knownSources);
        nextSources.add(e.source_type);
        set({ knownSources: nextSources });
      }
      if (state.source !== null && state.source !== e.source_type) return;
      if (state.items.length === 0) return;
      const resolution = get().resolution;
      const targetStart = bucketIndexFor(e.timestamp_ns, resolution);
      const lastIdx = state.items.length - 1;
      const last = state.items[lastIdx];

      if (targetStart < last.bucket_start_ns) return;

      if (targetStart === last.bucket_start_ns) {
        const ec = last.event_count + 1;
        const newMax = last.max_score === null ? e.score : Math.max(last.max_score, e.score);
        const prevSum = last.avg_score === null ? 0 : last.avg_score * last.event_count;
        const newAvg = (prevSum + e.score) / ec;
        const merged: TimelineBucket = {
          ...last,
          event_count: ec,
          max_score: newMax,
          avg_score: newAvg,
          upper_threshold: e.upper_threshold ?? last.upper_threshold,
        };
        const items = state.items.slice();
        items[lastIdx] = merged;
        set({ items });
        return;
      }

      const resNs = Number(RESOLUTION_NS[resolution]);
      const intermediates: TimelineBucket[] = [];
      for (let b = last.bucket_start_ns + resNs; b < targetStart; b += resNs) {
        intermediates.push({
          bucket_start_ns: b,
          max_score: null,
          avg_score: null,
          event_count: 0,
          upper_threshold: last.upper_threshold,
          alert_count: 0,
        });
      }
      const fresh: TimelineBucket = {
        bucket_start_ns: targetStart,
        max_score: e.score,
        avg_score: e.score,
        event_count: 1,
        upper_threshold: e.upper_threshold ?? last.upper_threshold,
        alert_count: 0,
      };
      // Ring-buffer bounded push: avoid intermediate concat allocation.
      // Only slice when adding fresh data would exceed capacity.
      // Apply cap to full output to handle gaps exceeding MAX_ITEMS.
      const combined = [...intermediates, fresh];
      const raw = [...state.items, ...combined];
      const next = raw.length <= MAX_ITEMS ? raw : raw.slice(-MAX_ITEMS);
      set({ items: next });
    },

    rolloverIfStale: (nowNs) => {
      const state = get();
      if (state.items.length === 0) return;
      const last = state.items[state.items.length - 1];
      const resNs = Number(RESOLUTION_NS[state.resolution]);
      if (nowNs - last.bucket_start_ns < resNs) return;
      const targetStart = Math.floor(nowNs / resNs) * resNs;
      const intermediates: TimelineBucket[] = [];
      for (let b = last.bucket_start_ns + resNs; b <= targetStart; b += resNs) {
        intermediates.push({
          bucket_start_ns: b,
          max_score: null,
          avg_score: null,
          event_count: 0,
          upper_threshold: last.upper_threshold,
          alert_count: 0,
        });
      }
      if (intermediates.length === 0) return;
      const raw = [...state.items, ...intermediates];
      const nextItems = raw.length <= MAX_ITEMS ? raw : raw.slice(-MAX_ITEMS);
      set({ items: nextItems });
    },
  }));
}

export const useAnomalyStore = createAnomalyStore();

/** Selector for distinct source types observed via live WS events. */
export function selectKnownSources(state: AnomalyState): string[] {
  return Array.from(state.knownSources);
}

/** Reset the store to its initial state. For use in ``beforeEach``. */
export function resetAnomalyStore(): void {
  useAnomalyStore.setState({
    ...INITIAL_STATE,
    knownSources: new Set<string>(),
    alertCountTruncated: false,
  });
}
