// frontend/src/lib/schemas.test.ts
import { describe, it, expect } from "vitest";
import * as v from "valibot";
import { LiveEventSchema, AlertSchema, AlertDetailSchema } from "./schemas";

const validEvent = {
  event_id: "e1",
  timestamp_ns: 100n,
  observed_ns: 100n,
  severity_id: 3,
  severity_text: "info",
  source_type: "syslog",
  message: "hello",
  template_id: 7,
  entity_refs: [],
  entity_summary: { ips: ["1.2.3.4"] },
};

const validAlert = {
  alert_id: "a1",
  timestamp_ns: 100n,
  alert_type: "sigma" as const,
  rule_name: "r",
  severity: 3,
  risk_score: 0.5,
  entity_uuid: null,
  entity_type: null,
  entity_value: null,
  message: "m",
  mitre_tactics: [],
  mitre_techniques: [],
  dedup_count: 1,
};

describe("LiveEventSchema", () => {
  it("accepts a valid LiveEvent", () => {
    expect(v.safeParse(LiveEventSchema, validEvent).success).toBe(true);
  });

  it("rejects severity_id out of 0..6 range", () => {
    expect(v.safeParse(LiveEventSchema, { ...validEvent, severity_id: 999 }).success).toBe(false);
  });

  it("rejects NaN / Infinity in score", () => {
    expect(v.safeParse(LiveEventSchema, { ...validEvent, score: Number.NaN }).success).toBe(false);
    expect(v.safeParse(LiveEventSchema, { ...validEvent, score: Number.POSITIVE_INFINITY }).success).toBe(false);
  });

  it("rejects oversize message", () => {
    expect(v.safeParse(LiveEventSchema, { ...validEvent, message: "x".repeat(16 * 1024 + 1) }).success).toBe(false);
  });

  it("rejects unknown entity_summary keys", () => {
    expect(v.safeParse(LiveEventSchema, { ...validEvent, entity_summary: { weird: ["x"] } }).success).toBe(false);
  });

  it("rejects non-bigint timestamp_ns", () => {
    expect(v.safeParse(LiveEventSchema, { ...validEvent, timestamp_ns: "100" }).success).toBe(false);
  });
});

describe("AlertSchema", () => {
  it("accepts a valid Alert", () => {
    expect(v.safeParse(AlertSchema, validAlert).success).toBe(true);
  });

  it("rejects severity out of 0..6", () => {
    expect(v.safeParse(AlertSchema, { ...validAlert, severity: 7 }).success).toBe(false);
  });

  it("rejects risk_score > 1", () => {
    expect(v.safeParse(AlertSchema, { ...validAlert, risk_score: 1.5 }).success).toBe(false);
  });

  it("rejects unknown alert_type", () => {
    expect(v.safeParse(AlertSchema, { ...validAlert, alert_type: "bogus" }).success).toBe(false);
  });

  it("rejects mitre_tactics entries that don't match [A-Z][A-Z0-9.-]{0,31}", () => {
    expect(v.safeParse(AlertSchema, { ...validAlert, mitre_tactics: ["lowercase"] }).success).toBe(false);
  });

  it("rejects oversize message", () => {
    expect(v.safeParse(AlertSchema, { ...validAlert, message: "x".repeat(16 * 1024 + 1) }).success).toBe(false);
  });
});

describe("AlertDetailSchema", () => {
  it("accepts an AlertDetail with contributing_events", () => {
    const detail = {
      ...validAlert,
      contributing_events: [{ event_id: "e1", timestamp_ns: 1n, message: "x" }],
    };
    expect(v.safeParse(AlertDetailSchema, detail).success).toBe(true);
  });

  it("rejects contributing_events over 50", () => {
    const detail = {
      ...validAlert,
      contributing_events: Array.from({ length: 51 }, (_, i) => ({
        event_id: `e${i}`,
        timestamp_ns: 1n,
        message: "x",
      })),
    };
    expect(v.safeParse(AlertDetailSchema, detail).success).toBe(false);
  });
});
