import { describe, expect, it } from "vitest";
import { createAnomalyStore } from "./anomaly";
import type { TimelineBucket, AnomalyEvent } from "@/lib/types";

const bucket = (overrides: Partial<TimelineBucket>): TimelineBucket => ({
  bucket_start_ns: 0,
  max_score: null,
  avg_score: null,
  event_count: 0,
  upper_threshold: null,
  alert_count: 0,
  ...overrides,
});

describe("anomalyStore", () => {
  it("defaults to 1h / 1m / all sources", () => {
    const s = createAnomalyStore().getState();
    expect(s.range).toBe("1h");
    expect(s.resolution).toBe("1m");
    expect(s.source).toBeNull();
    expect(s.items).toEqual([]);
    expect(s.loading).toBe(false);
    expect(s.error).toBeNull();
  });

  it("setRange snaps resolution to the default for the new range", () => {
    const store = createAnomalyStore();
    store.getState().setRange("7d");
    expect(store.getState().range).toBe("7d");
    expect(store.getState().resolution).toBe("15m");
  });

  it("setResolution sets resolution", () => {
    const store = createAnomalyStore();
    store.getState().setResolution("5m");
    expect(store.getState().resolution).toBe("5m");
  });

  it("setSource sets source filter", () => {
    const store = createAnomalyStore();
    store.getState().setSource("syslog");
    expect(store.getState().source).toBe("syslog");
    store.getState().setSource(null);
    expect(store.getState().source).toBeNull();
  });

  it("setLoading and setError update state", () => {
    const store = createAnomalyStore();
    store.getState().setLoading(true);
    expect(store.getState().loading).toBe(true);
    store.getState().setError("boom");
    expect(store.getState().error).toBe("boom");
  });

  it("replaceSeries replaces items wholesale", () => {
    const store = createAnomalyStore();
    store.getState().replaceSeries([bucket({ bucket_start_ns: 100 })]);
    expect(store.getState().items).toHaveLength(1);
    store.getState().replaceSeries([bucket({ bucket_start_ns: 200 }), bucket({ bucket_start_ns: 300 })]);
    expect(store.getState().items).toHaveLength(2);
    expect(store.getState().items[0].bucket_start_ns).toBe(200);
  });

  it("appendScore merges into the last bucket when indexes match", () => {
    const store = createAnomalyStore();
    store.getState().replaceSeries([bucket({ bucket_start_ns: 0, event_count: 1, max_score: 0.2, avg_score: 0.2, upper_threshold: 0.9 })]);
    const e: AnomalyEvent = { timestamp_ns: 30_000_000_000, score: 0.6, upper_threshold: 0.9, source_type: "syslog" };
    store.getState().appendScore(e);
    const last = store.getState().items.at(-1)!;
    expect(last.event_count).toBe(2);
    expect(last.max_score).toBe(0.6);
    expect(last.avg_score).toBeCloseTo((0.2 + 0.6) / 2);
  });

  it("appendScore creates a new bucket when the event lands in a newer bucket", () => {
    const store = createAnomalyStore();
    store.getState().replaceSeries([bucket({ bucket_start_ns: 0, event_count: 1, max_score: 0.2, avg_score: 0.2, upper_threshold: 0.9 })]);
    const e: AnomalyEvent = { timestamp_ns: 61_000_000_000, score: 0.3, upper_threshold: 0.95, source_type: "syslog" };
    store.getState().appendScore(e);
    const items = store.getState().items;
    expect(items).toHaveLength(2);
    expect(items.at(-1)!.bucket_start_ns).toBe(60_000_000_000);
    expect(items.at(-1)!.upper_threshold).toBe(0.95);
  });

  it("appendScore carries forward threshold across gaps", () => {
    const store = createAnomalyStore();
    store.getState().replaceSeries([bucket({ bucket_start_ns: 0, event_count: 1, max_score: 0.2, avg_score: 0.2, upper_threshold: 0.9 })]);
    // 3 minutes ahead -> gap of 2 intermediate empty buckets.
    const e: AnomalyEvent = { timestamp_ns: 180_000_000_000, score: 0.3, upper_threshold: null, source_type: "syslog" };
    store.getState().appendScore(e);
    const items = store.getState().items;
    expect(items).toHaveLength(4);
    expect(items[1].bucket_start_ns).toBe(60_000_000_000);
    expect(items[1].event_count).toBe(0);
    expect(items[1].upper_threshold).toBe(0.9);
    expect(items.at(-1)!.upper_threshold).toBe(0.9);
  });

  it("appendScore drops events older than the live-tail bucket (no retroactive edits)", () => {
    const store = createAnomalyStore();
    store.getState().replaceSeries([bucket({ bucket_start_ns: 60_000_000_000, event_count: 0 })]);
    const oldEvent: AnomalyEvent = { timestamp_ns: 30_000_000_000, score: 0.9, upper_threshold: 0.9, source_type: "syslog" };
    store.getState().appendScore(oldEvent);
    expect(store.getState().items).toHaveLength(1);
    expect(store.getState().items[0].event_count).toBe(0);
  });

  it("appendScore is a no-op when items is empty (waits for warm-up)", () => {
    const store = createAnomalyStore();
    const e: AnomalyEvent = { timestamp_ns: 0, score: 0.5, upper_threshold: 0.9, source_type: "syslog" };
    store.getState().appendScore(e);
    expect(store.getState().items).toHaveLength(0);
  });

  it("appendScore filters by the current source selection", () => {
    const store = createAnomalyStore();
    store.getState().replaceSeries([bucket({ bucket_start_ns: 0 })]);
    store.getState().setSource("syslog");
    const other: AnomalyEvent = { timestamp_ns: 0, score: 0.5, upper_threshold: 0.9, source_type: "otlp" };
    store.getState().appendScore(other);
    expect(store.getState().items[0].event_count).toBe(0);
  });

  it("appendScore under capacity appends without trimming", () => {
    const store = createAnomalyStore();
    store.getState().replaceSeries([bucket({ bucket_start_ns: 0, event_count: 1, max_score: 0.2, avg_score: 0.2, upper_threshold: 0.9 })]);
    const e: AnomalyEvent = { timestamp_ns: 61_000_000_000, score: 0.3, upper_threshold: 0.9, source_type: "syslog" };
    store.getState().appendScore(e);
    expect(store.getState().items.length).toBe(2);
    expect(store.getState().items[0].bucket_start_ns).toBe(0);
  });

  it("appendScore at capacity evicts oldest buckets", () => {
    const store = createAnomalyStore();
    const base = 0;
    const oneMinNs = 60_000_000_000;
    const full: import("@/lib/types").TimelineBucket[] = [];
    for (let i = 0; i < 2016; i++) {
      full.push(bucket({ bucket_start_ns: base + i * oneMinNs, event_count: 1, max_score: 0.1, avg_score: 0.1, upper_threshold: 0.9 }));
    }
    store.getState().replaceSeries(full);
    expect(store.getState().items.length).toBe(2016);

    const e: AnomalyEvent = {
      timestamp_ns: (base + 2016 * oneMinNs) + 1_000_000_000,
      score: 0.5,
      upper_threshold: 0.9,
      source_type: "syslog",
    };
    store.getState().appendScore(e);
    const items = store.getState().items;
    expect(items.length).toBe(2016);
    expect(items[0].bucket_start_ns).toBe(base + oneMinNs);
    expect(items.at(-1)!.max_score).toBe(0.5);
  });
});
