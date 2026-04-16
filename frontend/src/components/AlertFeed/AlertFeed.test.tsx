import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import { AlertFeed } from "./AlertFeed";
import { useAlertStore } from "@/stores/alerts";
import { logger } from "@/lib/logger";

const fetchMock = vi.fn();
vi.mock("@/lib/api", () => ({
  api: { get: (...a: unknown[]) => fetchMock("GET", ...a), post: vi.fn() },
  ApiError: class ApiError extends Error {},
}));

class MockWS {
  static last: MockWS | null = null;
  readyState = 0;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  sent: unknown[] = [];
  constructor() { MockWS.last = this; }
  send(d: string) { this.sent.push(JSON.parse(d)); }
  close() { this.readyState = 3; this.onclose?.(); }
  _open() { this.readyState = 1; this.onopen?.(); }
  _msg(m: unknown) { this.onmessage?.({ data: JSON.stringify(m) }); }
}

describe("AlertFeed integration", () => {
  beforeEach(() => {
    vi.stubGlobal("WebSocket", MockWS as unknown as typeof WebSocket);
    fetchMock.mockReset();
    MockWS.last = null;
    useAlertStore.setState({ alerts: [], status: "connecting", dropped: 0, selectedAlertId: null });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("warm-up then live alert appears at top", async () => {
    fetchMock.mockResolvedValueOnce({ items: [
      { alert_id: "warm", timestamp_ns: 1n, alert_type: "ml", rule_name: "warmup-rule",
        severity: 9, risk_score: 0.1, entity_uuid: null, entity_type: null,
        entity_value: null, message: "", mitre_tactics: [], mitre_techniques: [],
        dedup_count: 1, source_type: "syslog" },
    ] });
    render(<AlertFeed />);
    await waitFor(() => expect(screen.getByText("warmup-rule")).toBeInTheDocument());
    act(() => {
      MockWS.last!._open();
      MockWS.last!._msg({ type: "alert", data: {
        alert_id: "live", timestamp_ns: "2", alert_type: "sigma", rule_name: "live-rule",
        severity: 17, risk_score: 0.9, entity_uuid: null, entity_type: null,
        entity_value: null, message: "", mitre_tactics: [], mitre_techniques: [],
        dedup_count: 1, source_type: "syslog",
      } });
    });
    expect(screen.getByText("live-rule")).toBeInTheDocument();
  });

  it("buffers WS messages until warm-up resolves, then replays them (S-194 AC-3)", async () => {
    // Defer the warm-up REST promise so we can emit a WS frame first.
    let resolveWarmup: (value: { items: unknown[] }) => void = () => {};
    const warmupPromise = new Promise<{ items: unknown[] }>(r => { resolveWarmup = r; });
    fetchMock.mockReturnValueOnce(warmupPromise);

    render(<AlertFeed />);

    // WS frame arrives BEFORE warm-up resolves.
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    act(() => {
      MockWS.last!._open();
      MockWS.last!._msg({ type: "alert", data: {
        alert_id: "live", timestamp_ns: "2", alert_type: "sigma", rule_name: "live-rule",
        severity: 17, risk_score: 0.9, entity_uuid: null, entity_type: null,
        entity_value: null, message: "", mitre_tactics: [], mitre_techniques: [],
        dedup_count: 1, source_type: "syslog",
      } });
    });

    // The live frame must NOT be visible yet — warm-up hasn't resolved.
    expect(screen.queryByText("live-rule")).toBeNull();

    // Now resolve warm-up with an older alert.
    await act(async () => {
      resolveWarmup({ items: [
        { alert_id: "warm", timestamp_ns: 1n, alert_type: "ml", rule_name: "warmup-rule",
          severity: 9, risk_score: 0.1, entity_uuid: null, entity_type: null,
          entity_value: null, message: "", mitre_tactics: [], mitre_techniques: [],
          dedup_count: 1, source_type: "syslog" },
      ] });
      await warmupPromise;
    });

    // Both alerts now visible; the buffered live frame replayed AFTER backfill.
    await waitFor(() => expect(screen.getByText("live-rule")).toBeInTheDocument());
    expect(screen.getByText("warmup-rule")).toBeInTheDocument();
  });

  it("resets warmedUp on unmount so a remount re-buffers WS frames (S-194 AC-3 regression)", async () => {
    // First mount: warm-up resolves, WS frame goes through immediately.
    fetchMock.mockResolvedValueOnce({ items: [] });
    const { unmount } = render(<AlertFeed />);
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    act(() => { MockWS.last!._open(); });
    await new Promise(r => setTimeout(r, 0)); // let warm-up promise resolve
    unmount();

    // Second mount: warm-up is deferred; WS frame must be buffered, not visible.
    let resolveWarmup: (v: { items: unknown[] }) => void = () => {};
    const warmupPromise = new Promise<{ items: unknown[] }>(r => { resolveWarmup = r; });
    fetchMock.mockReturnValueOnce(warmupPromise);
    useAlertStore.setState({ alerts: [], detail: {}, dropped: 0, selectedAlertId: null });

    render(<AlertFeed />);
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    act(() => {
      MockWS.last!._open();
      MockWS.last!._msg({ type: "alert", data: {
        alert_id: "remounted", timestamp_ns: "1", alert_type: "ml", rule_name: "remount-rule",
        severity: 9, risk_score: 0.1, entity_uuid: null, entity_type: null,
        entity_value: null, message: "", mitre_tactics: [], mitre_techniques: [],
        dedup_count: 1, source_type: "syslog",
      } });
    });
    expect(screen.queryByText("remount-rule")).toBeNull();

    await act(async () => { resolveWarmup({ items: [] }); await warmupPromise; });
    await waitFor(() => expect(screen.getByText("remount-rule")).toBeInTheDocument());
  });

  it("caps wsBufferRef during slow warm-up so a WS storm cannot OOM the tab (S-194)", async () => {
    let resolveWarmup: (v: { items: unknown[] }) => void = () => {};
    const warmupPromise = new Promise<{ items: unknown[] }>(r => { resolveWarmup = r; });
    fetchMock.mockReturnValueOnce(warmupPromise);
    const warn = vi.spyOn(logger, "warn").mockImplementation(() => {});

    render(<AlertFeed />);
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    act(() => { MockWS.last!._open(); });

    // Pump 250 frames (limit is 200) before warm-up resolves.
    await act(async () => {
      for (let i = 0; i < 250; i++) {
        MockWS.last!._msg({ type: "alert", data: {
          alert_id: `a${i}`, timestamp_ns: String(i + 1), alert_type: "ml", rule_name: `r${i}`,
          severity: 9, risk_score: 0.1, entity_uuid: null, entity_type: null,
          entity_value: null, message: "", mitre_tactics: [], mitre_techniques: [],
          dedup_count: 1, source_type: "syslog",
        } });
      }
    });

    expect(warn).toHaveBeenCalled();  // overflow logged

    await act(async () => { resolveWarmup({ items: [] }); await warmupPromise; });
    // After replay, store should hold at most MAX_WS_BUFFER (200) of the 250 sent.
    await waitFor(() => {
      expect(useAlertStore.getState().alerts.length).toBeLessThanOrEqual(200);
    });
  });
});
