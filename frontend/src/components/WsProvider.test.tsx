import { render, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { WsProvider, useWsSend } from "./WsProvider";
import * as bus from "@/lib/wsBus";
import { logger } from "@/lib/logger";

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
  bus._clearAllForTests();
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
    const { createFilterSlot, _resetForTests } = await import("@/lib/wsFilter");
    _resetForTests();
    const alerts = createFilterSlot("alerts");
    alerts.set({ sources: ["auth"] });
    render(<WsProvider><div /></WsProvider>);
    act(() => { FakeSocket.lastInstance!.onopen?.(); });
    const first = JSON.parse(FakeSocket.lastInstance!.sent[0]!);
    expect(first).toEqual({ type: "filter", sources: ["auth"] });
  });

  describe("WsProvider reconnect regression", () => {
    let _resetForTests: () => void;

    beforeEach(async () => {
      const mod = await import("@/lib/wsFilter");
      _resetForTests = mod._resetForTests;
      _resetForTests();
    });

    afterEach(() => {
      _resetForTests();
      vi.useRealTimers();
    });

    it("re-emits __status:open and replays merged filter (regression lock)", async () => {
      const { createFilterSlot } = await import("@/lib/wsFilter");
      const alerts = createFilterSlot("alerts");
      alerts.set({ sources: ["syslog"] });

      vi.useFakeTimers();
      const statusFrames: string[] = [];
      const off = bus.on("__status", (msg) => { statusFrames.push(msg.status); });

      render(<WsProvider><div /></WsProvider>);

      // First open — filter replay + __status:open
      act(() => { FakeSocket.lastInstance!.onopen?.(); });
      const firstFilterFrames = FakeSocket.lastInstance!.sent.filter(
        (s) => JSON.parse(s).type === "filter",
      );
      expect(firstFilterFrames).toHaveLength(1);
      expect(JSON.parse(firstFilterFrames[0]!)).toEqual({ type: "filter", sources: ["syslog"] });
      expect(statusFrames.filter((s) => s === "open")).toHaveLength(1);

      // Close — hook schedules reconnect with BACKOFF_MS[0] = 1000 ms
      act(() => { FakeSocket.lastInstance!.onclose?.(); });
      expect(statusFrames.filter((s) => s === "closed")).toHaveLength(1);

      // Advance past the first backoff delay so the hook fires setTimeout(connect, 1000)
      act(() => { vi.advanceTimersByTime(1000); });

      // Second open on the new socket
      act(() => { FakeSocket.lastInstance!.onopen?.(); });
      const secondFilterFrames = FakeSocket.lastInstance!.sent.filter(
        (s) => JSON.parse(s).type === "filter",
      );
      expect(secondFilterFrames).toHaveLength(1);
      expect(JSON.parse(secondFilterFrames[0]!)).toEqual({ type: "filter", sources: ["syslog"] });
      expect(statusFrames.filter((s) => s === "open")).toHaveLength(2);

      off();
    });
  });

  it("useWsSend() throws when called outside the provider", () => {
    function Consumer(): JSX.Element { useWsSend(); return <div />; }
    // Mute React's error boundary console output for this case.
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(() => render(<Consumer />)).toThrow(/useWsSend/i);
    spy.mockRestore();
  });
});

describe("resolveUrl origin allowlist", () => {
  const origBase = import.meta.env.VITE_API_BASE;
  const origAllow = import.meta.env.VITE_WS_ORIGIN_ALLOWLIST;
  let origLocation: Location;

  beforeEach(() => {
    origLocation = window.location;
  });

  afterEach(() => {
    (import.meta.env as Record<string, unknown>).VITE_API_BASE = origBase;
    (import.meta.env as Record<string, unknown>).VITE_WS_ORIGIN_ALLOWLIST = origAllow;
    // Always restore window.location so an assertion failure in a sibling test
    // doesn't poison the rest of the describe block.
    Object.defineProperty(window, "location", { writable: true, value: origLocation });
  });

  it("allows same-origin by default", () => {
    (import.meta.env as Record<string, unknown>).VITE_API_BASE = window.location.origin;
    (import.meta.env as Record<string, unknown>).VITE_WS_ORIGIN_ALLOWLIST = "";
    expect(() => render(<WsProvider><div /></WsProvider>)).not.toThrow();
  });

  it("throws on cross-origin when allowlist is empty", () => {
    (import.meta.env as Record<string, unknown>).VITE_API_BASE = "https://evil.example";
    (import.meta.env as Record<string, unknown>).VITE_WS_ORIGIN_ALLOWLIST = "";
    // Mute React's error boundary console output for this case.
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(() => render(<WsProvider><div /></WsProvider>)).toThrow(/not in VITE_WS_ORIGIN_ALLOWLIST/);
    spy.mockRestore();
  });

  it("permits cross-origin when listed in allowlist", () => {
    (import.meta.env as Record<string, unknown>).VITE_API_BASE = "https://api.seerflow.io";
    (import.meta.env as Record<string, unknown>).VITE_WS_ORIGIN_ALLOWLIST = "https://api.seerflow.io,https://stg.seerflow.io";
    expect(() => render(<WsProvider><div /></WsProvider>)).not.toThrow();
  });

  it("upgrades ws: to wss: when page is served over https", () => {
    Object.defineProperty(window, "location", {
      writable: true,
      value: { ...window.location, protocol: "https:", origin: "https://dash.local" },
    });
    (import.meta.env as Record<string, unknown>).VITE_API_BASE = "https://dash.local";
    (import.meta.env as Record<string, unknown>).VITE_WS_ORIGIN_ALLOWLIST = "";

    // Same-origin https: resolved url starts "wss:" because base replace /^http/ -> ws
    // gives "wss://..." already — the upgrade branch is not hit but render must not throw.
    expect(() => render(<WsProvider><div /></WsProvider>)).not.toThrow();
  });

  it("logs when VITE_API_BASE is plain http: under https page (ws: upgrade branch)", () => {
    const warnSpy = vi.spyOn(logger, "warn");
    Object.defineProperty(window, "location", {
      writable: true,
      value: { ...window.location, protocol: "https:", origin: "http://dash.local" },
    });
    (import.meta.env as Record<string, unknown>).VITE_API_BASE = "http://dash.local";
    (import.meta.env as Record<string, unknown>).VITE_WS_ORIGIN_ALLOWLIST = "";

    expect(() => render(<WsProvider><div /></WsProvider>)).not.toThrow();
    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining("upgrading to wss:"),
      expect.any(String),
    );

    warnSpy.mockRestore();
  });

  it("normalises allowlist entries to lowercase", () => {
    (import.meta.env as Record<string, unknown>).VITE_API_BASE = "https://api.seerflow.io";
    (import.meta.env as Record<string, unknown>).VITE_WS_ORIGIN_ALLOWLIST = "HTTPS://Api.Seerflow.IO";
    expect(() => render(<WsProvider><div /></WsProvider>)).not.toThrow();
  });

  it("falls back to window.location.origin when VITE_API_BASE is empty string", () => {
    (import.meta.env as Record<string, unknown>).VITE_API_BASE = "";
    (import.meta.env as Record<string, unknown>).VITE_WS_ORIGIN_ALLOWLIST = "";
    expect(() => render(<WsProvider><div /></WsProvider>)).not.toThrow();
  });
});
