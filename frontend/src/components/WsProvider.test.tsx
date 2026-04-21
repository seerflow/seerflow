import { render, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { WsProvider, useWsSend } from "./WsProvider";
import * as bus from "@/lib/wsBus";

class FakeSocket {
  static lastInstance: FakeSocket | null = null;
  onopen: (() => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 1;
  sent: string[] = [];
  constructor(public url: string) { FakeSocket.lastInstance = this; }
  send(data: string): void { this.sent.push(data); }
  close(): void { this.onclose?.(); }
}

beforeEach(() => {
  vi.stubGlobal("WebSocket", FakeSocket as unknown as typeof WebSocket);
  bus.clearAll();
});
afterEach(() => { vi.unstubAllGlobals(); });

function ConsumeSend(): JSX.Element {
  const send = useWsSend();
  return <button onClick={() => send({ type: "ping" })}>go</button>;
}

describe("WsProvider", () => {
  it("opens exactly one socket on mount and closes on unmount", () => {
    const { unmount } = render(<WsProvider><div /></WsProvider>);
    expect(FakeSocket.lastInstance).not.toBeNull();
    const close = vi.spyOn(FakeSocket.lastInstance!, "close");
    unmount();
    expect(close).toHaveBeenCalledTimes(1);
  });

  it("emits parsed status messages to wsBus by discriminated type", () => {
    const statusHandler = vi.fn();
    bus.on("status", statusHandler);
    render(<WsProvider><div /></WsProvider>);
    act(() => { FakeSocket.lastInstance!.onopen?.(); });
    act(() => {
      FakeSocket.lastInstance!.onmessage?.(new MessageEvent("message", {
        data: JSON.stringify({
          type: "status",
          data: {
            events_ingested_per_sec: 5, alerts_24h: 2,
            connected_clients: 1, dropped_events: 0,
            dropped_alerts: 0, dropped_total: 0,
          },
        }),
      }));
    });
    expect(statusHandler).toHaveBeenCalledTimes(1);
  });

  it("emits a synthetic __status bus frame when useWebSocket status changes", () => {
    const h = vi.fn();
    bus.on("__status", h);
    render(<WsProvider><div /></WsProvider>);
    act(() => { FakeSocket.lastInstance!.onopen?.(); });
    // onStatusChange("connecting") + onStatusChange("open"), both re-emitted to bus.
    expect(h).toHaveBeenCalled();
    const lastCall = h.mock.calls[h.mock.calls.length - 1][0];
    expect(lastCall).toEqual({ type: "__status", status: "open" });
  });

  it("exposes useWsSend() that queues before open and flushes on open", () => {
    const { getByText } = render(
      <WsProvider><ConsumeSend /></WsProvider>,
    );
    // Click before fake socket fires onopen — the hook should queue.
    getByText("go").click();
    expect(FakeSocket.lastInstance!.sent).toHaveLength(0);
    act(() => { FakeSocket.lastInstance!.onopen?.(); });
    // On open useWebSocket sends the merged filter first (empty → `{type:"filter"}`)
    // and then flushes the queued ping.
    expect(FakeSocket.lastInstance!.sent).toEqual([
      JSON.stringify({ type: "filter" }),
      JSON.stringify({ type: "ping" }),
    ]);
  });

  it("replays the merged wsFilter on every (re)connect via getFilterMessage", async () => {
    const { setIntent } = await import("@/lib/wsFilter");
    setIntent("alerts", { sources: ["auth"] });
    render(<WsProvider><div /></WsProvider>);
    act(() => { FakeSocket.lastInstance!.onopen?.(); });
    const first = JSON.parse(FakeSocket.lastInstance!.sent[0]!);
    expect(first).toEqual({ type: "filter", sources: ["auth"] });
  });

  it("useWsSend() throws when called outside the provider", () => {
    function Consumer(): JSX.Element { useWsSend(); return <div />; }
    // Mute React's error boundary console output for this case.
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(() => render(<Consumer />)).toThrow(/useWsSend/i);
    spy.mockRestore();
  });
});
