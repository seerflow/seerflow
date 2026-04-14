import { describe, it, expect } from "vitest";
import { createAlertStore, selectVisible, selectCounts } from "./alerts";
import type { Alert } from "@/lib/types";

const a = (overrides: Partial<Alert> = {}): Alert => ({
  alert_id: "1", timestamp_ns: 1, alert_type: "ml", rule_name: "r",
  severity: 17, risk_score: 0.9, entity_uuid: null, entity_type: null,
  entity_value: null, message: "m", mitre_tactics: [], mitre_techniques: [],
  dedup_count: 1, source_type: "syslog", ...overrides,
});

describe("alertStore", () => {
  it("prepend bounds to MAX_ALERTS", () => {
    const s = createAlertStore(3);
    for (let i = 0; i < 5; i++) s.getState().prepend(a({alert_id: String(i), timestamp_ns: i}));
    expect(s.getState().alerts.map(x => x.alert_id)).toEqual(["4","3","2"]);
  });

  it("dedup merges by alert_id, keeps newer timestamp", () => {
    const s = createAlertStore(10);
    s.getState().prepend(a({alert_id: "x", timestamp_ns: 5, dedup_count: 1}));
    s.getState().prepend(a({alert_id: "x", timestamp_ns: 10, dedup_count: 3}));
    expect(s.getState().alerts).toHaveLength(1);
    expect(s.getState().alerts[0]).toMatchObject({timestamp_ns: 10, dedup_count: 3});
  });

  it("backfill preserves order newest first and bounds", () => {
    const s = createAlertStore(3);
    s.getState().backfill([a({alert_id: "1", timestamp_ns: 1}), a({alert_id: "2", timestamp_ns: 2}), a({alert_id: "3", timestamp_ns: 3}), a({alert_id: "4", timestamp_ns: 4})]);
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
