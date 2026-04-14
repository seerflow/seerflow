import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useWebSocket } from "./useWebSocket";

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
    act(() => { ws._msg({ type: "alert", data: {} }); });
    expect(onMessage).toHaveBeenCalledWith({ type: "alert", data: {} });
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
