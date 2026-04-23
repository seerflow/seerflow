// frontend/src/lib/schemas.test.ts
import { describe, it, expect, beforeEach, vi } from "vitest";
import * as v from "valibot";
import {
  LiveEventSchema,
  AlertSchema,
  AlertDetailSchema,
  parseWsFrame,
} from "./schemas";
import * as metrics from "./validationMetrics";
import { logger } from "./logger";

vi.mock("./logger", () => ({ logger: { warn: vi.fn(), info: vi.fn(), error: vi.fn() } }));

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

  it("rejects entity_refs over 128 items", () => {
    const big = { ...validEvent, entity_refs: Array.from({ length: 129 }, (_, i) => `e${i}`) };
    expect(v.safeParse(LiveEventSchema, big).success).toBe(false);
  });

  it("rejects entity_summary.ips over 64 items", () => {
    const big = { ...validEvent, entity_summary: { ips: Array.from({ length: 65 }, (_, i) => `1.2.3.${i}`) } };
    expect(v.safeParse(LiveEventSchema, big).success).toBe(false);
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

  it("rejects entity_uuid over 64 chars", () => {
    expect(v.safeParse(AlertSchema, { ...validAlert, entity_uuid: "x".repeat(65) }).success).toBe(false);
  });

  it("rejects mitre_tactics over 32 items", () => {
    const big = { ...validAlert, mitre_tactics: Array.from({ length: 33 }, (_, i) => `TA${String(i).padStart(4, "0")}`) };
    expect(v.safeParse(AlertSchema, big).success).toBe(false);
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

describe("parseWsFrame", () => {
  beforeEach(() => {
    metrics._resetForTests();
    (logger.warn as ReturnType<typeof vi.fn>).mockClear();
  });

  const wireAlert = {
    type: "alert",
    data: {
      alert_id: "a1",
      timestamp_ns: "100",
      alert_type: "sigma",
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
    },
  };

  it("converts a valid wire alert frame into a revived WsMessage", () => {
    const out = parseWsFrame(wireAlert);
    expect(out).not.toBeNull();
    expect(out!.type).toBe("alert");
    if (out!.type === "alert") {
      expect(out!.data.timestamp_ns).toBe(100n);
    }
  });

  it("drops a frame with severity 999 and increments counter", () => {
    const bad = { ...wireAlert, data: { ...wireAlert.data, severity: 999 } };
    const out = parseWsFrame(bad);
    expect(out).toBeNull();
    expect(metrics.getCounters()["ws:alert"]).toBe(1);
  });

  it("drops a frame with unknown top-level type under ws:unknown", () => {
    const out = parseWsFrame({ type: "weird", foo: 1 });
    expect(out).toBeNull();
    expect(metrics.getCounters()["ws:unknown"]).toBe(1);
  });

  it("drops and counts a wire event with too-long message", () => {
    const wireEvent = {
      type: "event",
      data: {
        event_id: "e1",
        timestamp_ns: "100",
        observed_ns: "100",
        severity_id: 3,
        severity_text: "info",
        source_type: "syslog",
        message: "x".repeat(16 * 1024 + 1),
        template_id: 7,
        entity_refs: [],
        entity_summary: {},
      },
    };
    expect(parseWsFrame(wireEvent)).toBeNull();
    expect(metrics.getCounters()["ws:event"]).toBe(1);
  });

  it("caps alert_batch at 100", () => {
    const batch = {
      type: "alert_batch",
      alerts: Array.from({ length: 101 }, (_, i) => ({ ...wireAlert.data, alert_id: `a${i}` })),
    };
    expect(parseWsFrame(batch)).toBeNull();
    expect(metrics.getCounters()["ws:alert_batch"]).toBe(1);
  });

  it("revives a valid wire event frame into bigint timestamps", () => {
    const wireEvent = {
      type: "event",
      data: {
        event_id: "e1",
        timestamp_ns: "100",
        observed_ns: "200",
        severity_id: 3,
        severity_text: "info",
        source_type: "syslog",
        message: "hello",
        template_id: 7,
        entity_refs: [],
        entity_summary: { ips: ["1.2.3.4"] },
      },
    };
    const out = parseWsFrame(wireEvent);
    expect(out).not.toBeNull();
    if (out && out.type === "event") {
      expect(out.data.timestamp_ns).toBe(100n);
      expect(out.data.observed_ns).toBe(200n);
    }
  });

  it("accepts a valid status frame without bigint revival", () => {
    const wireStatus = {
      type: "status",
      data: {
        events_ingested_per_sec: 1,
        alerts_24h: 2,
        connected_clients: 3,
        dropped_events: 0,
        dropped_alerts: 0,
        dropped_total: 0,
      },
    };
    const out = parseWsFrame(wireStatus);
    expect(out).not.toBeNull();
    expect(out?.type).toBe("status");
  });

  it("revives a valid alert_batch frame with 2 alerts", () => {
    const batch = {
      type: "alert_batch",
      alerts: [
        { ...wireAlert.data, alert_id: "a1" },
        { ...wireAlert.data, alert_id: "a2" },
      ],
    };
    const out = parseWsFrame(batch);
    expect(out).not.toBeNull();
    if (out && out.type === "alert_batch") {
      expect(out.alerts).toHaveLength(2);
      expect(out.alerts[0].timestamp_ns).toBe(100n);
      expect(out.alerts[1].timestamp_ns).toBe(100n);
    }
  });

  it("revives a heterogeneous batch of one event and one alert", () => {
    const mixed = {
      type: "batch",
      events: [
        {
          event_id: "e1",
          timestamp_ns: "100",
          observed_ns: "200",
          severity_id: 3,
          severity_text: "info",
          source_type: "syslog",
          message: "hello",
          template_id: 7,
          entity_refs: [],
          entity_summary: {},
        },
        { ...wireAlert.data, alert_id: "a1" },
      ],
    };
    const out = parseWsFrame(mixed);
    expect(out).not.toBeNull();
    if (out && out.type === "batch") {
      expect(out.events).toHaveLength(2);
      // LiveEvent has observed_ns, Alert does not — use that to discriminate
      const [first, second] = out.events;
      expect("observed_ns" in first).toBe(true);
      expect("alert_type" in second).toBe(true);
      expect((first as { timestamp_ns: bigint }).timestamp_ns).toBe(100n);
      expect((second as { timestamp_ns: bigint }).timestamp_ns).toBe(100n);
    }
  });
});
