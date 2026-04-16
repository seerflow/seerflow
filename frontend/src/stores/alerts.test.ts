import { describe, it, expect } from "vitest";
import { createAlertStore, selectVisible, selectCounts, selectVisibleAndCounts } from "./alerts";
import type { Alert } from "@/lib/types";

const a = (overrides: Partial<Alert> = {}): Alert => ({
  alert_id: "1", timestamp_ns: 1n, alert_type: "ml", rule_name: "r",
  severity: 17, risk_score: 0.9, entity_uuid: null, entity_type: null,
  entity_value: null, message: "m", mitre_tactics: [], mitre_techniques: [],
  dedup_count: 1, source_type: "syslog", ...overrides,
});

describe("alertStore", () => {
  it("prepend bounds to MAX_ALERTS", () => {
    const s = createAlertStore(3);
    for (let i = 0; i < 5; i++) s.getState().prepend(a({alert_id: String(i), timestamp_ns: BigInt(i)}));
    expect(s.getState().alerts.map(x => x.alert_id)).toEqual(["4","3","2"]);
  });

  it("dedup merges by alert_id, keeps newer timestamp", () => {
    const s = createAlertStore(10);
    s.getState().prepend(a({alert_id: "x", timestamp_ns: 5n, dedup_count: 1}));
    s.getState().prepend(a({alert_id: "x", timestamp_ns: 10n, dedup_count: 3}));
    expect(s.getState().alerts).toHaveLength(1);
    expect(s.getState().alerts[0]).toMatchObject({timestamp_ns: 10n, dedup_count: 3});
  });

  it("backfill preserves order newest first and bounds", () => {
    const s = createAlertStore(3);
    s.getState().backfill([a({alert_id: "1", timestamp_ns: 1n}), a({alert_id: "2", timestamp_ns: 2n}), a({alert_id: "3", timestamp_ns: 3n}), a({alert_id: "4", timestamp_ns: 4n})]);
    expect(s.getState().alerts.map(x => x.alert_id)).toEqual(["4","3","2"]);
  });

  it("selectVisible applies severity filter", () => {
    const s = createAlertStore(10);
    s.getState().prepend(a({alert_id: "c", severity: 17}));
    s.getState().prepend(a({alert_id: "l", severity: 2}));
    s.getState().setFilter({severities: new Set(["critical"])});
    expect(selectVisible(s.getState()).map(x => x.alert_id)).toEqual(["c"]);
  });

  it("selectCounts returns per-bucket counts", () => {
    const s = createAlertStore(10);
    s.getState().prepend(a({alert_id: "1", severity: 17}));
    s.getState().prepend(a({alert_id: "2", severity: 13}));
    s.getState().prepend(a({alert_id: "3", severity: 5}));
    expect(selectCounts(s.getState())).toEqual({total: 3, critical: 1, high: 1, medium: 0, low: 1});
  });

  it("setFeedback updates in place", () => {
    const s = createAlertStore(10);
    s.getState().prepend(a({alert_id: "1"}));
    s.getState().setFeedback("1", "tp");
    expect(s.getState().alerts[0].feedback).toBe("tp");
  });
});

describe("alertStore selectedAlertId slice", () => {
  it("selectAlert sets the id; clearSelection resets it", () => {
    const store = createAlertStore();
    expect(store.getState().selectedAlertId).toBeNull();
    store.getState().selectAlert("abc");
    expect(store.getState().selectedAlertId).toBe("abc");
    store.getState().clearSelection();
    expect(store.getState().selectedAlertId).toBeNull();
  });
});

describe("selectVisibleAndCounts (S-194 AC-5)", () => {
  it("selectVisibleAndCounts returns one-pass {visible, counts} (S-194 AC-5)", () => {
    const s = createAlertStore(10);
    s.getState().backfill([
      a({ alert_id: "crit", severity: 18, timestamp_ns: 3n }),  // critical (>=17)
      a({ alert_id: "high", severity: 14, timestamp_ns: 2n }),  // high     (>=13)
      a({ alert_id: "med",  severity: 10, timestamp_ns: 1n }),  // medium   (>=9)
    ]);
    const r = selectVisibleAndCounts(s.getState());
    expect(r.visible.map(x => x.alert_id)).toEqual(["crit", "high", "med"]);
    expect(r.counts).toEqual({ total: 3, critical: 1, high: 1, medium: 1, low: 0 });
  });

  it("selectVisibleAndCounts caches by (alerts, filter) reference identity (S-194 AC-5)", () => {
    const s = createAlertStore(10);
    s.getState().backfill([a({ alert_id: "x", severity: 18, timestamp_ns: 1n })]);
    const a1 = selectVisibleAndCounts(s.getState());
    const a2 = selectVisibleAndCounts(s.getState());
    // Same store state -> same returned object reference (cache hit).
    expect(a1).toBe(a2);
  });
});

describe("alertStore bigint timestamp_ns (S-194 AC-1)", () => {
  it("preserves bigint timestamp_ns through prepend (S-194 AC-1)", () => {
    const s = createAlertStore(10);
    s.getState().prepend(a({ alert_id: "boundary", timestamp_ns: 1_700_000_000_000_000_123n }));
    expect(s.getState().alerts[0].timestamp_ns).toBe(1_700_000_000_000_000_123n);
  });

  it("sorts bigint timestamps newest-first via backfill (S-194 AC-1)", () => {
    const s = createAlertStore(10);
    s.getState().backfill([
      a({ alert_id: "old",    timestamp_ns: 1_700_000_000_000_000_000n }),
      a({ alert_id: "newest", timestamp_ns: 1_700_000_000_000_000_999n }),
      a({ alert_id: "mid",    timestamp_ns: 1_700_000_000_000_000_500n }),
    ]);
    expect(s.getState().alerts.map(x => x.alert_id)).toEqual(["newest", "mid", "old"]);
  });
});
