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

  setRange: (r: TimelineRange) => void;
  setResolution: (r: TimelineResolution) => void;
  setSource: (s: string | null) => void;
  replaceSeries: (items: TimelineBucket[]) => void;
  appendScore: (e: AnomalyEvent, resolution: TimelineResolution) => void;
  setLoading: (b: boolean) => void;
  setError: (s: string | null) => void;
}

const MAX_ITEMS = 2016;

function bucketIndexFor(ts_ns: number, resolution: TimelineResolution): number {
  return Number(bucketStartNs(BigInt(ts_ns), resolution));
}

export function createAnomalyStore(): UseBoundStore<StoreApi<AnomalyState>> {
  return create<AnomalyState>((set, get) => ({
    range: "1h",
    resolution: "1m",
    source: null,
    items: [],
    loading: false,
    error: null,

    setRange: (r) => set({ range: r, resolution: defaultResolution(r) }),
    setResolution: (r) => set({ resolution: r }),
    setSource: (s) => set({ source: s }),
    replaceSeries: (items) => set({ items: items.slice(-MAX_ITEMS) }),
    setLoading: (b) => set({ loading: b }),
    setError: (s) => set({ error: s }),

    appendScore: (e, resolution) => {
      const state = get();
      if (state.source !== null && state.source !== e.source_type) return;
      if (state.items.length === 0) return;
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
      const next = state.items.concat(intermediates, fresh).slice(-MAX_ITEMS);
      set({ items: next });
    },
  }));
}

export const useAnomalyStore = createAnomalyStore();
