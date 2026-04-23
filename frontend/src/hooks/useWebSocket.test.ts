import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useWebSocket } from "./useWebSocket";
import { logger } from "@/lib/logger";
import * as metrics from "@/lib/validationMetrics";

class MockWS {
  static instances: MockWS[] = [];
  readyState = 0;
  sent: unknown[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) { MockWS.instances.push(this); }
  send(d: string) { this.sent.push(JSON.parse(d)); }
  close() { this.readyState = 3; this.onclose?.(); }
  _open() { this.readyState = 1; this.onopen?.(); }
  _msg(m: unknown) { this.onmessage?.({ data: JSON.stringify(m) }); }
}

describe("useWebSocket", () => {
  beforeEach(() => { vi.useFakeTimers(); vi.stubGlobal("WebSocket", MockWS as unknown as typeof WebSocket); MockWS.instances = []; });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  it("dispatches messages", () => {
    const onMessage = vi.fn(); const onStatusChange = vi.fn();
    renderHook(() => useWebSocket("ws://x", { onMessage, onStatusChange }));
    const ws = MockWS.instances[0];
    act(() => { ws._open(); });
    expect(onStatusChange).toHaveBeenCalledWith("open");
    act(() => { ws._msg({ type: "status", data: { events_ingested_per_sec: 0, alerts_24h: 0, connected_clients: 0, dropped_events: 0, dropped_alerts: 0, dropped_total: 0 } }); });
    expect(onMessage).toHaveBeenCalled();
  });

  it("reconnects with exponential backoff", () => {
    const onMessage = vi.fn(); const onStatusChange = vi.fn();
    renderHook(() => useWebSocket("ws://x", { onMessage, onStatusChange }));
    act(() => { MockWS.instances[0]._open(); MockWS.instances[0].close(); });
    expect(MockWS.instances).toHaveLength(1);
    act(() => { vi.advanceTimersByTime(1000); });
    expect(MockWS.instances).toHaveLength(2);
    act(() => { MockWS.instances[1].close(); vi.advanceTimersByTime(2000); });
    expect(MockWS.instances).toHaveLength(3);
  });

  it("resends filter on reconnect", () => {
    const getFilterMessage = () => ({ type: "filter" as const, min_severity: 13 });
    renderHook(() => useWebSocket("ws://x", { onMessage: vi.fn(), onStatusChange: vi.fn(), getFilterMessage }));
    const ws0 = MockWS.instances[0]; act(() => { ws0._open(); });
    expect(ws0.sent).toEqual([{ type: "filter", min_severity: 13 }]);
    act(() => { ws0.close(); vi.advanceTimersByTime(1000); });
    const ws1 = MockWS.instances[1]; act(() => { ws1._open(); });
    expect(ws1.sent).toEqual([{ type: "filter", min_severity: 13 }]);
  });
});

describe("useWebSocket schema validation (S-194)", () => {
  beforeEach(() => { vi.useFakeTimers(); vi.stubGlobal("WebSocket", MockWS as unknown as typeof WebSocket); MockWS.instances = []; metrics._resetForTests(); });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it("drops malformed alert frames with logger.warn (S-194 AC-2)", () => {
    const warn = vi.spyOn(logger, "warn").mockImplementation(() => {});
    const onMessage = vi.fn();
    renderHook(() => useWebSocket("ws://x", { onMessage, onStatusChange: vi.fn() }));
    const ws = MockWS.instances[0]; act(() => { ws._open(); });

    act(() => { ws._msg({ type: "alert", data: { alert_id: 7 } }); });
    expect(onMessage).not.toHaveBeenCalled();
    expect(warn).toHaveBeenCalled();
  });

  it("drops messages with unknown type (S-194 AC-2)", () => {
    const warn = vi.spyOn(logger, "warn").mockImplementation(() => {});
    const onMessage = vi.fn();
    renderHook(() => useWebSocket("ws://x", { onMessage, onStatusChange: vi.fn() }));
    const ws = MockWS.instances[0]; act(() => { ws._open(); });

    act(() => { ws._msg({ type: "garbage", data: {} }); });
    expect(onMessage).not.toHaveBeenCalled();
    expect(warn).toHaveBeenCalled();
  });

  it("converts alert.data.timestamp_ns string to bigint (S-194 AC-1)", () => {
    const onMessage = vi.fn();
    renderHook(() => useWebSocket("ws://x", { onMessage, onStatusChange: vi.fn() }));
    const ws = MockWS.instances[0]; act(() => { ws._open(); });

    act(() => { ws._msg({
      type: "alert",
      data: {
        alert_id: "a1", timestamp_ns: "1700000000000000123", alert_type: "ml",
        rule_name: "r", severity: 5, risk_score: 0,
        entity_uuid: "u", entity_type: "ip", entity_value: "x",
        message: "m", mitre_tactics: [], mitre_techniques: [], dedup_count: 1,
      },
    }); });

    expect(onMessage).toHaveBeenCalledOnce();
    const arg = onMessage.mock.calls[0][0];
    expect(arg.type).toBe("alert");
    expect(arg.data.timestamp_ns).toBe(1700000000000000123n);
  });

  it("passes status frames through unchanged (S-194 AC-2 happy path)", () => {
    const onMessage = vi.fn();
    renderHook(() => useWebSocket("ws://x", { onMessage, onStatusChange: vi.fn() }));
    const ws = MockWS.instances[0]; act(() => { ws._open(); });

    act(() => { ws._msg({ type: "status", data: {
      events_ingested_per_sec: 10, alerts_24h: 5, connected_clients: 1, dropped_events: 0, dropped_alerts: 0, dropped_total: 0,
    } }); });
    expect(onMessage).toHaveBeenCalledOnce();
  });

  it("accepts real backend status frame shape (regression: events_ingested_per_sec, dropped_total)", () => {
    const onMessage = vi.fn();
    renderHook(() => useWebSocket("ws://x", { onMessage, onStatusChange: vi.fn() }));
    const ws = MockWS.instances[0]; act(() => { ws._open(); });
    act(() => { ws._msg({ type: "status", data: {
      events_ingested_per_sec: 100, alerts_24h: 5, connected_clients: 1,
      dropped_events: 0, dropped_alerts: 0, dropped_total: 0,
    } }); });
    expect(onMessage).toHaveBeenCalledOnce();
  });

  it("accepts and converts alert_batch frames (regression: previously dropped)", () => {
    const onMessage = vi.fn();
    renderHook(() => useWebSocket("ws://x", { onMessage, onStatusChange: vi.fn() }));
    const ws = MockWS.instances[0]; act(() => { ws._open(); });
    act(() => { ws._msg({ type: "alert_batch", alerts: [
      { alert_id: "a1", timestamp_ns: "1700000000000000123", alert_type: "ml", rule_name: "r", severity: 5, risk_score: 0, entity_uuid: "u", entity_type: "ip", entity_value: "x", message: "m", mitre_tactics: [], mitre_techniques: [], dedup_count: 1 },
      { alert_id: "a2", timestamp_ns: "1700000000000000456", alert_type: "sigma", rule_name: "r", severity: 6, risk_score: 0, entity_uuid: "u", entity_type: "ip", entity_value: "x", message: "m", mitre_tactics: [], mitre_techniques: [], dedup_count: 1 },
    ] }); });
    expect(onMessage).toHaveBeenCalledOnce();
    const arg = onMessage.mock.calls[0][0];
    expect(arg.type).toBe("alert_batch");
    expect(arg.alerts).toHaveLength(2);
    expect(arg.alerts[0].timestamp_ns).toBe(1700000000000000123n);
  });

  it("rejects alert frame with non-numeric timestamp_ns string at the schema layer", () => {
    const warn = vi.spyOn(logger, "warn").mockImplementation(() => {});
    const onMessage = vi.fn();
    renderHook(() => useWebSocket("ws://x", { onMessage, onStatusChange: vi.fn() }));
    const ws = MockWS.instances[0]; act(() => { ws._open(); });
    act(() => { ws._msg({ type: "alert", data: {
      alert_id: "a1", timestamp_ns: "not-a-number", alert_type: "ml", rule_name: "r",
      severity: 10, risk_score: 0, entity_uuid: "u", entity_type: "ip", entity_value: "x",
      message: "m", mitre_tactics: [], mitre_techniques: [], dedup_count: 1,
    } }); });
    expect(onMessage).not.toHaveBeenCalled();
    expect(warn).toHaveBeenCalled();
  });

  it("drops alert_batch frames longer than 100 alerts (S-203 AC-4)", () => {
    const warn = vi.spyOn(logger, "warn").mockImplementation(() => {});
    const onMessage = vi.fn();
    renderHook(() => useWebSocket("ws://x", { onMessage, onStatusChange: vi.fn() }));
    const ws = MockWS.instances[0]; act(() => { ws._open(); });

    const oversized = {
      type: "alert_batch",
      alerts: Array.from({ length: 101 }, (_, i) => ({
        alert_id: `a${i}`,
        timestamp_ns: "1700000000000000000",
      })),
    };
    act(() => { ws._msg(oversized); });
    expect(onMessage).not.toHaveBeenCalled();
    expect(warn).toHaveBeenCalled();
  });

  it("accepts alert_batch frames at the 100-alert cap (S-203 AC-4)", () => {
    const onMessage = vi.fn();
    renderHook(() => useWebSocket("ws://x", { onMessage, onStatusChange: vi.fn() }));
    const ws = MockWS.instances[0]; act(() => { ws._open(); });

    const ok = {
      type: "alert_batch",
      alerts: Array.from({ length: 100 }, (_, i) => ({
        alert_id: `a${i}`,
        timestamp_ns: "1700000000000000000",
        alert_type: "ml",
        rule_name: "r",
        severity: 3,
        risk_score: 0,
        entity_uuid: "u",
        entity_type: "ip",
        entity_value: "x",
        message: "m",
        mitre_tactics: [],
        mitre_techniques: [],
        dedup_count: 1,
      })),
    };
    act(() => { ws._msg(ok); });
    expect(onMessage).toHaveBeenCalledTimes(1);
    // Each alert's timestamp_ns should be a bigint after the existing conversion in useWebSocket.
    const dispatched = onMessage.mock.calls[0][0];
    expect(dispatched.type).toBe("alert_batch");
    expect(typeof dispatched.alerts[0].timestamp_ns).toBe("bigint");
    expect(dispatched.alerts).toHaveLength(100);
  });
});

describe("useWebSocket event arm (S-199)", () => {
  beforeEach(() => { vi.useFakeTimers(); vi.stubGlobal("WebSocket", MockWS as unknown as typeof WebSocket); MockWS.instances = []; metrics._resetForTests(); });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it("parses event timestamp_ns + observed_ns strings into bigint (S-199 AC-6)", () => {
    const onMessage = vi.fn();
    renderHook(() => useWebSocket("ws://x", { onMessage, onStatusChange: vi.fn() }));
    const ws = MockWS.instances[0]; act(() => { ws._open(); });

    act(() => {
      ws._msg({
        type: "event",
        data: {
          event_id: "e1",
          timestamp_ns: "1700000000000000123",
          observed_ns:  "1700000000000000456",
          severity_id: 5,
          severity_text: "ERROR",
          source_type: "syslog",
          message: "m",
          template_id: 7,
          entity_refs: [],
          entity_summary: {},
        },
      });
    });

    expect(onMessage).toHaveBeenCalledOnce();
    const payload = onMessage.mock.calls[0][0];
    expect(payload.type).toBe("event");
    expect(payload.data.timestamp_ns).toBe(1700000000000000123n);
    expect(payload.data.observed_ns).toBe(1700000000000000456n);
  });

  it("drops event frames with missing timestamp_ns (S-199 AC-6)", () => {
    const warn = vi.spyOn(logger, "warn").mockImplementation(() => {});
    const onMessage = vi.fn();
    renderHook(() => useWebSocket("ws://x", { onMessage, onStatusChange: vi.fn() }));
    const ws = MockWS.instances[0]; act(() => { ws._open(); });

    act(() => { ws._msg({ type: "event", data: { event_id: "e1" } }); });
    expect(onMessage).not.toHaveBeenCalled();
    expect(warn).toHaveBeenCalled();
  });

  it("rejects event frames with over-long timestamp_ns strings (S-199 DoS guard)", () => {
    const warn = vi.spyOn(logger, "warn").mockImplementation(() => {});
    const onMessage = vi.fn();
    renderHook(() => useWebSocket("ws://x", { onMessage, onStatusChange: vi.fn() }));
    const ws = MockWS.instances[0]; act(() => { ws._open(); });

    // 26-digit string exceeds MAX_NS_STRING_LEN (25). Valibot regex must reject
    // before BigInt() is ever called — guards against BigInt-allocation DoS.
    act(() => { ws._msg({
      type: "event",
      data: {
        event_id: "e-dos",
        timestamp_ns: "1".repeat(26),
        observed_ns: "1700000000000000000",
      },
    }); });
    expect(onMessage).not.toHaveBeenCalled();
    expect(warn).toHaveBeenCalled();
  });

  it("drops batch frames containing over-long timestamp_ns at the schema layer (S-191 DoS guard)", () => {
    const warn = vi.spyOn(logger, "warn").mockImplementation(() => {});
    const onMessage = vi.fn();
    renderHook(() => useWebSocket("ws://x", { onMessage, onStatusChange: vi.fn() }));
    const ws = MockWS.instances[0]; act(() => { ws._open(); });

    // After S-191 migration to parseWsFrame, batch events are validated against
    // LiveEventWireSchema/AlertWireSchema which enforce the 1..25 digit regex on
    // timestamp_ns. A crafted 50-digit string fails the wire regex and the entire
    // frame is dropped — stronger protection than the previous pass-through path.
    act(() => { ws._msg({
      type: "batch",
      events: [{ event_id: "e1", timestamp_ns: "1".repeat(50), observed_ns: "1700000000000000000" }],
    }); });
    expect(onMessage).not.toHaveBeenCalled();
    expect(warn).toHaveBeenCalled();
  });
});

describe("useWebSocket send queue (S-204)", () => {
  beforeEach(() => { vi.useFakeTimers(); vi.stubGlobal("WebSocket", MockWS as unknown as typeof WebSocket); MockWS.instances = []; metrics._resetForTests(); });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it("queues messages sent before the socket opens and flushes on open (S-204 AC-4b)", () => {
    const { result } = renderHook(() => useWebSocket("ws://x", { onMessage: vi.fn(), onStatusChange: vi.fn() }));
    const ws = MockWS.instances[0];
    act(() => { result.current.send({ hello: 1 }); });
    expect(ws.sent).toEqual([]);
    act(() => { ws._open(); });
    expect(ws.sent).toEqual([{ hello: 1 }]);
  });

  it("warns and drops frames with invalid JSON payload (S-204 AC-4 coverage closure)", () => {
    const warn = vi.spyOn(logger, "warn").mockImplementation(() => {});
    const onMessage = vi.fn();
    renderHook(() => useWebSocket("ws://x", { onMessage, onStatusChange: vi.fn() }));
    const ws = MockWS.instances[0];
    act(() => { ws._open(); });
    act(() => { ws.onmessage?.({ data: "{not-json" }); });
    expect(onMessage).not.toHaveBeenCalled();
    expect(warn).toHaveBeenCalledWith("ws parse fail", expect.any(Error));
  });
});

describe("useWebSocket parseWsFrame delegation (S-191)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", MockWS as unknown as typeof WebSocket);
    MockWS.instances = [];
    metrics._resetForTests();
  });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it("drops a frame with unknown top-level type and counts it under ws:unknown", () => {
    vi.spyOn(logger, "warn").mockImplementation(() => {});
    const onMessage = vi.fn();
    renderHook(() => useWebSocket("ws://x", { onMessage, onStatusChange: vi.fn() }));
    const ws = MockWS.instances[0];
    act(() => { ws._open(); });

    act(() => { ws._msg({ type: "weird" }); });

    expect(onMessage).not.toHaveBeenCalled();
    expect(metrics.getCounters()["ws:unknown"]).toBe(1);
  });

  it("drops a frame with severity 999 and counts it under ws:alert", () => {
    vi.spyOn(logger, "warn").mockImplementation(() => {});
    const onMessage = vi.fn();
    renderHook(() => useWebSocket("ws://x", { onMessage, onStatusChange: vi.fn() }));
    const ws = MockWS.instances[0];
    act(() => { ws._open(); });

    act(() => { ws._msg({
      type: "alert",
      data: {
        alert_id: "a1",
        timestamp_ns: "1700000000000000123",
        alert_type: "ml",
        rule_name: "r",
        severity: 999,
        risk_score: 0,
        entity_uuid: "u",
        entity_type: "ip",
        entity_value: "x",
        message: "m",
        mitre_tactics: [],
        mitre_techniques: [],
        dedup_count: 1,
      },
    }); });

    expect(onMessage).not.toHaveBeenCalled();
    expect(metrics.getCounters()["ws:alert"]).toBe(1);
  });
});
