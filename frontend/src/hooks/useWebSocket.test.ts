import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useWebSocket } from "./useWebSocket";
import { logger } from "@/lib/logger";

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
    act(() => { ws._msg({ type: "status", data: { events_per_sec: 0, alerts_24h: 0, connected_clients: 0, dropped_messages: 0 } }); });
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
  beforeEach(() => { vi.useFakeTimers(); vi.stubGlobal("WebSocket", MockWS as unknown as typeof WebSocket); MockWS.instances = []; });
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
        rule_name: "r", severity: 10, risk_score: 0,
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
      events_per_sec: 10, alerts_24h: 5, connected_clients: 1, dropped_messages: 0,
    } }); });
    expect(onMessage).toHaveBeenCalledOnce();
  });
});
