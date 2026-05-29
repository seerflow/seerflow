import { describe, it, expect } from "vitest";
import type { Alert } from "@/lib/types";
import { deriveTopRiskEntities } from "./topRiskEntities";

function alert(over: Partial<Alert> = {}): Alert {
  return {
    alert_id: "a1",
    timestamp_ns: 1n,
    alert_type: "sigma",
    rule_name: "r",
    severity: 5,
    risk_score: 0.5,
    entity_uuid: "u1",
    entity_type: "ip",
    entity_value: "10.0.0.1",
    message: "m",
    mitre_tactics: [],
    mitre_techniques: [],
    dedup_count: 1,
    ...over,
  };
}

describe("deriveTopRiskEntities", () => {
  it("returns [] for no alerts", () => {
    expect(deriveTopRiskEntities([])).toEqual([]);
  });

  it("skips alerts with no entity", () => {
    const out = deriveTopRiskEntities([
      alert({ entity_uuid: null }),
      alert({ entity_value: null }),
    ]);
    expect(out).toEqual([]);
  });

  it("groups by entity_uuid: max risk, summed events, counted alerts", () => {
    const out = deriveTopRiskEntities([
      alert({ alert_id: "a1", entity_uuid: "u1", risk_score: 0.4, dedup_count: 3 }),
      alert({ alert_id: "a2", entity_uuid: "u1", risk_score: 0.9, dedup_count: 2 }),
    ]);
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({
      id: "u1",
      name: "10.0.0.1",
      kind: "ip",
      risk: 0.9,
      eventCount: 5,
      alertCount: 2,
    });
  });

  it("sorts by risk descending and caps at 7", () => {
    const alerts = Array.from({ length: 10 }, (_, i) =>
      alert({ alert_id: `a${i}`, entity_uuid: `u${i}`, entity_value: `e${i}`, risk_score: i / 10 }),
    );
    const out = deriveTopRiskEntities(alerts);
    expect(out).toHaveLength(7);
    expect(out[0].risk).toBe(0.9);
    expect(out.map((e) => e.risk)).toEqual([...out.map((e) => e.risk)].sort((a, b) => b - a));
  });

  it("falls back to 'host' kind when entity_type is null", () => {
    const out = deriveTopRiskEntities([alert({ entity_type: null })]);
    expect(out[0].kind).toBe("host");
  });
});
