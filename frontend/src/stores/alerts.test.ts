import { describe, it, expect } from "vitest";
import { createAlertStore, selectVisibleAndCounts } from "./alerts";
import type { Alert } from "@/lib/types";

const a = (overrides: Partial<Alert> = {}): Alert => ({
  alert_id: "1", timestamp_ns: 1n, alert_type: "ml", rule_name: "r",
  severity: 6, risk_score: 0.9, entity_uuid: null, entity_type: null,
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

  it("dedup keeps newer fields when incoming has older timestamp_ns (S-204 AC-1, mergePrepend)", () => {
    const s = createAlertStore(10);
    s.getState().prepend(a({alert_id: "x", timestamp_ns: 10n, message: "new", dedup_count: 1}));
    s.getState().prepend(a({alert_id: "x", timestamp_ns: 5n,  message: "old", dedup_count: 5}));
    expect(s.getState().alerts).toHaveLength(1);
    expect(s.getState().alerts[0]).toMatchObject({timestamp_ns: 10n, message: "new", dedup_count: 5});
  });

  it("dedup keeps newer fields when backfill brings older timestamp_ns (S-204 AC-1, backfill)", () => {
    const s = createAlertStore(10);
    s.getState().prepend(a({alert_id: "x", timestamp_ns: 10n, message: "new", dedup_count: 1}));
    s.getState().backfill([a({alert_id: "x", timestamp_ns: 5n, message: "old", dedup_count: 5})]);
    expect(s.getState().alerts).toHaveLength(1);
    expect(s.getState().alerts[0]).toMatchObject({timestamp_ns: 10n, message: "new", dedup_count: 5});
  });

  it("dedup takes newer fields when backfill brings newer timestamp_ns (S-204 AC-1, backfill newer branch)", () => {
    const s = createAlertStore(10);
    s.getState().prepend(a({alert_id: "x", timestamp_ns: 5n, message: "old", dedup_count: 1}));
    s.getState().backfill([a({alert_id: "x", timestamp_ns: 10n, message: "new", dedup_count: 5})]);
    expect(s.getState().alerts).toHaveLength(1);
    expect(s.getState().alerts[0]).toMatchObject({timestamp_ns: 10n, message: "new", dedup_count: 5});
  });

  it("backfill preserves order newest first and bounds", () => {
    const s = createAlertStore(3);
    s.getState().backfill([a({alert_id: "1", timestamp_ns: 1n}), a({alert_id: "2", timestamp_ns: 2n}), a({alert_id: "3", timestamp_ns: 3n}), a({alert_id: "4", timestamp_ns: 4n})]);
    expect(s.getState().alerts.map(x => x.alert_id)).toEqual(["4","3","2"]);
  });

  it("filters by severity (S-203, formerly selectVisible)", () => {
    const s = createAlertStore(10);
    s.getState().prepend(a({alert_id: "c", severity: 6}));
    s.getState().prepend(a({alert_id: "l", severity: 1}));
    s.getState().setFilter({severities: new Set(["critical"])});
    expect(selectVisibleAndCounts(s.getState()).visible.map(x => x.alert_id)).toEqual(["c"]);
  });

  it("returns per-bucket counts (S-203, formerly selectCounts)", () => {
    const s = createAlertStore(10);
    s.getState().prepend(a({alert_id: "1", severity: 6}));  // critical (>=5)
    s.getState().prepend(a({alert_id: "2", severity: 4}));  // high     (=4)
    s.getState().prepend(a({alert_id: "3", severity: 1}));  // low      (<=2)
    expect(selectVisibleAndCounts(s.getState()).counts).toEqual({total: 3, critical: 1, high: 1, medium: 0, low: 1});
  });

  it("setFeedback updates in place", () => {
    const s = createAlertStore(10);
    s.getState().prepend(a({alert_id: "1"}));
    s.getState().setFeedback("1", "tp");
    expect(s.getState().alerts[0].feedback).toBe("tp");
  });

  it("bumpFeedbackVersion increments per alertId (S-066)", () => {
    const s = createAlertStore(10);
    s.getState().bumpFeedbackVersion("a-1");
    s.getState().bumpFeedbackVersion("a-1");
    s.getState().bumpFeedbackVersion("a-2");
    expect(s.getState().feedbackVersion["a-1"]).toBe(2);
    expect(s.getState().feedbackVersion["a-2"]).toBe(1);
  });

  it("setFeedback ignores unmatched alert_id (S-204 coverage closure)", () => {
    const s = createAlertStore(10);
    s.getState().prepend(a({alert_id: "1", feedback: undefined}));
    s.getState().setFeedback("other", "tp");
    expect(s.getState().alerts[0].feedback).toBeUndefined();
  });

  it("backfill preserves insertion order for equal timestamp_ns alerts (S-204 coverage closure)", () => {
    const s = createAlertStore(10);
    s.getState().backfill([a({alert_id: "a", timestamp_ns: 5n}), a({alert_id: "b", timestamp_ns: 5n})]);
    expect(s.getState().alerts.map(x => x.alert_id)).toEqual(["a", "b"]);
  });

  it("filters by alert_type and drops non-matching (S-204 coverage closure)", () => {
    const s = createAlertStore(10);
    s.getState().prepend(a({alert_id: "m", alert_type: "ml"}));
    s.getState().prepend(a({alert_id: "s", alert_type: "sigma"}));
    s.getState().setFilter({types: new Set(["ml"])});
    expect(selectVisibleAndCounts(s.getState()).visible.map(x => x.alert_id)).toEqual(["m"]);
  });

  it("filters by source_type and drops non-matching (S-204 coverage closure)", () => {
    const s = createAlertStore(10);
    s.getState().prepend(a({alert_id: "syslog", source_type: "syslog"}));
    s.getState().prepend(a({alert_id: "cloudtrail", source_type: "cloudtrail"}));
    s.getState().setFilter({sources: new Set(["syslog"])});
    expect(selectVisibleAndCounts(s.getState()).visible.map(x => x.alert_id)).toEqual(["syslog"]);
  });

  it("filters by mitre_tactic and drops non-matching (S-204 coverage closure)", () => {
    const s = createAlertStore(10);
    s.getState().prepend(a({alert_id: "ta1", mitre_tactics: ["TA0001"]}));
    s.getState().prepend(a({alert_id: "ta2", mitre_tactics: ["TA0002"]}));
    s.getState().setFilter({tactics: new Set(["TA0001"])});
    expect(selectVisibleAndCounts(s.getState()).visible.map(x => x.alert_id)).toEqual(["ta1"]);
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
      a({ alert_id: "crit", severity: 6, timestamp_ns: 3n }),  // critical (>=5)
      a({ alert_id: "high", severity: 4, timestamp_ns: 2n }),  // high     (=4)
      a({ alert_id: "med",  severity: 3, timestamp_ns: 1n }),  // medium   (=3)
    ]);
    const r = selectVisibleAndCounts(s.getState());
    expect(r.visible.map(x => x.alert_id)).toEqual(["crit", "high", "med"]);
    expect(r.counts).toEqual({ total: 3, critical: 1, high: 1, medium: 1, low: 0 });
  });

  it("selectVisibleAndCounts caches by (alerts, filter) reference identity (S-194 AC-5)", () => {
    const s = createAlertStore(10);
    s.getState().backfill([a({ alert_id: "x", severity: 5, timestamp_ns: 1n })]);
    const a1 = selectVisibleAndCounts(s.getState());
    const a2 = selectVisibleAndCounts(s.getState());
    // Same store state -> same returned object reference (cache hit).
    expect(a1).toBe(a2);
  });

  it("selectVisibleAndCounts cache is scoped per store instance (S-203 AC-1)", () => {
    const s1 = createAlertStore(10);
    const s2 = createAlertStore(10);
    s1.getState().backfill([a({ alert_id: "a", severity: 5 })]);  // critical
    s2.getState().backfill([a({ alert_id: "b", severity: 1 })]);  // low
    const s1_state = s1.getState();
    const s2_state = s2.getState();
    // s1_state and s2_state are different objects (zustand creates new state obj on each set)
    expect(s1_state).not.toBe(s2_state);
    const r1 = selectVisibleAndCounts(s1_state);
    const r2 = selectVisibleAndCounts(s2_state);
    expect(r1.counts).toEqual({ total: 1, critical: 1, high: 0, medium: 0, low: 0 });
    expect(r2.counts).toEqual({ total: 1, critical: 0, high: 0, medium: 0, low: 1 });
    // Re-entry against s1 must NOT return s2's value.
    const r1again = selectVisibleAndCounts(s1_state);
    expect(r1again).toBe(r1);
    expect(r1again.counts.critical).toBe(1);
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
