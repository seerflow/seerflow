import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import { AlertFeed } from "./AlertFeed";
import { WsProvider } from "@/components/WsProvider";
import { useAlertStore } from "@/stores/alerts";
import { logger } from "@/lib/logger";
import * as wsBus from "@/lib/wsBus";
import type { LiveEvent } from "@/lib/types";
import { _resetForTests as resetWsIntents } from "@/lib/wsFilter";
import { AlertSchema, validateOrDropItem } from "@/lib/schemas";
import * as validationMetrics from "@/lib/validationMetrics";
import { useAnomalyStore } from "@/stores/anomaly";

const { fetchMock } = vi.hoisted(() => ({ fetchMock: vi.fn() }));
vi.mock("@/lib/api", async () => {
  const { createApiMock } = await import("@/test/helpers/apiMock");
  return createApiMock({ fetchMock });
});

class MockWS {
  static last: MockWS | null = null;
  static OPEN = 1;
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

function renderWithProvider(): ReturnType<typeof render> {
  return render(<WsProvider><AlertFeed /></WsProvider>);
}

describe("AlertFeed integration", () => {
  beforeEach(() => {
    vi.stubGlobal("WebSocket", MockWS as unknown as typeof WebSocket);
    fetchMock.mockReset();
    MockWS.last = null;
    wsBus._clearAllForTests();
    wsBus._resetFrameBufferForTests();
    resetWsIntents();
    useAlertStore.setState({ alerts: [], filter: { severities: new Set(), types: new Set(), sources: new Set(), tactics: new Set() }, status: "connecting", dropped: 0, selectedAlertId: null });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("warm-up then live alert appears at top", async () => {
    fetchMock.mockResolvedValueOnce({ items: [
      { alert_id: "warm", timestamp_ns: 1n, alert_type: "ml", rule_name: "warmup-rule",
        severity: 5, risk_score: 0.1, entity_uuid: null, entity_type: null,
        entity_value: null, message: "", mitre_tactics: [], mitre_techniques: [],
        dedup_count: 1, source_type: "syslog" },
    ] });
    renderWithProvider();
    await waitFor(() => expect(screen.getByText("warmup-rule")).toBeInTheDocument());
    act(() => {
      MockWS.last!._open();
      MockWS.last!._msg({ type: "alert", data: {
        alert_id: "live", timestamp_ns: "2", alert_type: "sigma", rule_name: "live-rule",
        severity: 6, risk_score: 0.9, entity_uuid: null, entity_type: null,
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

    renderWithProvider();

    // WS frame arrives BEFORE warm-up resolves.
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    act(() => {
      MockWS.last!._open();
      MockWS.last!._msg({ type: "alert", data: {
        alert_id: "live", timestamp_ns: "2", alert_type: "sigma", rule_name: "live-rule",
        severity: 6, risk_score: 0.9, entity_uuid: null, entity_type: null,
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
          severity: 5, risk_score: 0.1, entity_uuid: null, entity_type: null,
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
    const { unmount } = renderWithProvider();
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    act(() => { MockWS.last!._open(); });
    await new Promise(r => setTimeout(r, 0)); // let warm-up promise resolve
    unmount();

    // Second mount: warm-up is deferred; WS frame must be buffered, not visible.
    let resolveWarmup: (v: { items: unknown[] }) => void = () => {};
    const warmupPromise = new Promise<{ items: unknown[] }>(r => { resolveWarmup = r; });
    fetchMock.mockReturnValueOnce(warmupPromise);
    useAlertStore.setState({ alerts: [], detail: {}, filter: { severities: new Set(), types: new Set(), sources: new Set(), tactics: new Set() }, dropped: 0, selectedAlertId: null });
    wsBus._clearAllForTests();

    renderWithProvider();
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    act(() => {
      MockWS.last!._open();
      MockWS.last!._msg({ type: "alert", data: {
        alert_id: "remounted", timestamp_ns: "1", alert_type: "ml", rule_name: "remount-rule",
        severity: 5, risk_score: 0.1, entity_uuid: null, entity_type: null,
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

    renderWithProvider();
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    act(() => { MockWS.last!._open(); });

    // Pump 250 frames (limit is 200) before warm-up resolves.
    await act(async () => {
      for (let i = 0; i < 250; i++) {
        MockWS.last!._msg({ type: "alert", data: {
          alert_id: `a${i}`, timestamp_ns: String(i + 1), alert_type: "ml", rule_name: `r${i}`,
          severity: 5, risk_score: 0.1, entity_uuid: null, entity_type: null,
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

  it("subscribes to wsBus __status so connection lifecycle updates the alert store status", async () => {
    fetchMock.mockResolvedValueOnce({ items: [] });
    renderWithProvider();
    await waitFor(() => expect(MockWS.last).not.toBeNull());

    // Simulate WsProvider emitting a __status frame onto the bus via the open event.
    act(() => { MockWS.last!._open(); });
    await waitFor(() => expect(useAlertStore.getState().status).toBe("open"));

    // Manually publish a closed __status to the bus — AlertFeed must mirror it.
    act(() => { wsBus.emit({ type: "__status", status: "closed" }); });
    expect(useAlertStore.getState().status).toBe("closed");
  });

  it("pushes merged filter payload through useWsSend after 150 ms debounce when filter changes", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fetchMock.mockResolvedValueOnce({ items: [] });
    renderWithProvider();
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    act(() => { MockWS.last!._open(); });
    MockWS.last!.sent.length = 0;

    // Switching the filter bucket schedules a 150 ms debounced filter push.
    act(() => {
      useAlertStore.setState({
        filter: { severities: new Set(["critical"]), types: new Set(), sources: new Set(), tactics: new Set() },
      });
    });
    // Before debounce expires, nothing sent yet.
    expect(MockWS.last!.sent).toEqual([]);
    await act(async () => { await vi.advanceTimersByTimeAsync(200); });
    const filterFrames = MockWS.last!.sent.filter(
      (m): m is { type: string; min_severity?: number } =>
        typeof m === "object" && m !== null && (m as { type?: unknown }).type === "filter",
    );
    expect(filterFrames.some(m => m.min_severity === 5)).toBe(true);
    vi.useRealTimers();
  });

  it("no longer listens for the legacy seerflow:wsfilter-changed CustomEvent", async () => {
    fetchMock.mockResolvedValueOnce({ items: [] });
    renderWithProvider();
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    act(() => { MockWS.last!._open(); });
    MockWS.last!.sent.length = 0;

    act(() => {
      window.dispatchEvent(new CustomEvent("seerflow:wsfilter-changed"));
    });

    expect(MockWS.last!.sent).toEqual([]);
  });

  it("does not ingest alerts arriving under type:'batch' (alerts ship via alert_batch)", async () => {
    fetchMock.mockResolvedValueOnce({ items: [] });
    renderWithProvider();
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    act(() => { MockWS.last!._open(); });
    // Let the warm-up promise resolve so subsequent bus emissions dispatch
    // straight through `handleMessage` instead of being parked in the buffer.
    await new Promise(r => setTimeout(r, 0));

    // bigint timestamp_ns: we bypass parseWsFrame, which is the layer that
    // would normally coerce the wire string → bigint, so the fixture has to
    // ship in domain-typed form.
    const mkAlert = (id: string, rule: string) => ({
      alert_id: id, timestamp_ns: 1n, alert_type: "ml" as const, rule_name: rule,
      severity: 5, risk_score: 0.1, entity_uuid: null, entity_type: null,
      entity_value: null, message: "", mitre_tactics: [], mitre_techniques: [],
      dedup_count: 1, source_type: "syslog",
    });
    // Bypass parseWsFrame on purpose — the wire schema validates `batch` as
    // LiveEvent-only and would drop this payload before it reached the bus.
    // The whole point of this regression test is to prove that AlertFeed's
    // bus subscription on `"batch"` is what re-introduces alert-shaped frames
    // via the dead `isAlert(first)` branch in `handleMessage` (AlertFeed.tsx
    // L73–L82). After Task 2 removes the subscription, the emit becomes a
    // no-op for AlertFeed and the assertion holds.
    //
    // Cast: `WsMessage.batch.events` is `LiveEvent[]` after S-211's narrowing.
    // We are deliberately violating that contract to prove the bus drops the
    // shape; the cast is the only way to express "emit a malformed batch."
    act(() => {
      wsBus.emit({ type: "batch", events: [mkAlert("ghost-1", "ghost-rule")] as unknown as LiveEvent[] });
    });

    expect(screen.queryByText("ghost-rule")).toBeNull();
  });

  it("handles alert_batch arrivals", async () => {
    fetchMock.mockResolvedValueOnce({ items: [] });
    renderWithProvider();
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    act(() => { MockWS.last!._open(); });

    const mkAlert = (id: string, rule: string) => ({
      alert_id: id, timestamp_ns: "1", alert_type: "ml" as const, rule_name: rule,
      severity: 5, risk_score: 0.1, entity_uuid: null, entity_type: null,
      entity_value: null, message: "", mitre_tactics: [], mitre_techniques: [],
      dedup_count: 1, source_type: "syslog",
    });
    act(() => {
      MockWS.last!._msg({ type: "alert_batch", alerts: [mkAlert("b1", "batch-rule-1"), mkAlert("b2", "batch-rule-2")] });
    });
    expect(screen.getByText("batch-rule-1")).toBeInTheDocument();
    expect(screen.getByText("batch-rule-2")).toBeInTheDocument();
  });

  it("uses h-full min-h-0 so the section fills its grid cell (no viewport calc)", async () => {
    fetchMock.mockResolvedValueOnce({ items: [] });
    const { container } = renderWithProvider();
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    const section = container.querySelector("section");
    expect(section).not.toBeNull();
    const cls = section!.className;
    expect(cls).toContain("h-full");
    expect(cls).toContain("min-h-0");
    expect(cls).not.toMatch(/h-\[calc\(/);
  });
});

describe("S-191 T9: REST warm-up schema validation", () => {
  beforeEach(() => {
    vi.stubGlobal("WebSocket", MockWS as unknown as typeof WebSocket);
    fetchMock.mockReset();
    MockWS.last = null;
    wsBus._clearAllForTests();
    // S-209: this describe dispatches `type: "event"` frames through WsProvider,
    // which now routes via wsBus.emitCoalesced → rafFrameBuffer. Reset the buffer
    // so a prior test's unflushed event cannot cross into the next test.
    wsBus._resetFrameBufferForTests();
    resetWsIntents();
    validationMetrics._resetForTests();
    useAlertStore.setState({
      alerts: [],
      filter: { severities: new Set(), types: new Set(), sources: new Set(), tactics: new Set() },
      status: "connecting",
      dropped: 0,
      selectedAlertId: null,
    });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("drops invalid REST items from /api/v1/alerts warm-up under rest:/api/v1/alerts", async () => {
    // NOTE: the mocked `api.get` runs `validateOrDropItem` with the same schema
    // AlertFeed passes in — so this test verifies the component wires the schema
    // through, which is what bumps the `rest:/api/v1/alerts` counter.
    const validFixture = {
      alert_id: "valid",
      timestamp_ns: 1n,
      alert_type: "ml" as const,
      rule_name: "valid-rule",
      severity: 5,
      risk_score: 0.1,
      entity_uuid: null,
      entity_type: null,
      entity_value: null,
      message: "",
      mitre_tactics: [],
      mitre_techniques: [],
      dedup_count: 1,
      source_type: "syslog",
    };
    // severity 999 fails AlertSchema (OCSF 0..6).
    const invalidFixture = { ...validFixture, alert_id: "bad", severity: 999 };
    fetchMock.mockResolvedValueOnce({ items: [validFixture, invalidFixture] });

    // Sanity: raw AlertSchema rejects the invalid fixture.
    expect(validateOrDropItem(AlertSchema, invalidFixture, "rest:test")).toBeNull();

    render(<WsProvider><AlertFeed /></WsProvider>);
    // Warm-up resolves asynchronously → wait for the store to land exactly the
    // valid alert; the invalid one must be dropped via rest:/api/v1/alerts.
    await waitFor(() => {
      expect(useAlertStore.getState().alerts.map(a => a.alert_id)).toEqual(["valid"]);
    });
    expect(validationMetrics.getCounters()["rest:/api/v1/alerts"]).toBe(1);
  });

  // S-209: WsProvider now routes `event` frames through wsBus.emitCoalesced,
  // which defers dispatch to the next animation frame. Tests that assert on
  // the appendScore fan-out wait for the rAF tick (jsdom's native rAF fires
  // on a ~16 ms timer) via `waitFor` before asserting.
  it("fans anomaly-scored `event` frames out to useAnomalyStore.appendScore", async () => {
    fetchMock.mockResolvedValueOnce({ items: [] });
    // Seed a bucket so appendScore has something to merge into.
    useAnomalyStore.setState({
      items: [{ bucket_start_ns: 0n, max_score: null, avg_score: null, event_count: 0, upper_threshold: null, alert_count: 0 }],
      source: null,
      knownSources: new Set(),
      resolution: "1m",
    });
    const spy = vi.spyOn(useAnomalyStore.getState(), "appendScore");

    render(<WsProvider><AlertFeed /></WsProvider>);
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    act(() => { MockWS.last!._open(); });
    // Give warm-up a tick to resolve so frames dispatch synchronously.
    await new Promise(r => setTimeout(r, 0));

    act(() => {
      MockWS.last!._msg({ type: "event", data: {
        event_id: "e1", timestamp_ns: "5", observed_ns: "5",
        severity_id: 3, severity_text: "MEDIUM", source_type: "syslog",
        message: "anom", template_id: 1, entity_refs: [], entity_summary: {},
        score: 0.9, is_anomaly: true, upper_threshold: 0.5,
      } });
    });
    // Wait for the rAF tick that wsBus.emitCoalesced schedules.
    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(spy).toHaveBeenCalledWith(expect.objectContaining({
      score: 0.9,
      source_type: "syslog",
      upper_threshold: 0.5,
    }));
  });

  it("ignores `event` frames without a score (chokepoint-validated but non-anomalous)", async () => {
    fetchMock.mockResolvedValueOnce({ items: [] });
    const spy = vi.spyOn(useAnomalyStore.getState(), "appendScore");

    render(<WsProvider><AlertFeed /></WsProvider>);
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    act(() => { MockWS.last!._open(); });
    await new Promise(r => setTimeout(r, 0));

    act(() => {
      MockWS.last!._msg({ type: "event", data: {
        event_id: "e2", timestamp_ns: "6", observed_ns: "6",
        severity_id: 2, severity_text: "LOW", source_type: "syslog",
        message: "plain", template_id: 1, entity_refs: [], entity_summary: {},
        // no score → the `d.score !== undefined` guard skips appendScore.
      } });
    });
    // Wait out the rAF tick that wsBus.emitCoalesced scheduled; piggyback on
    // jsdom's native rAF rather than a fixed-duration timer so a slow runner
    // cannot flake the negative assertion.
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    expect(spy).not.toHaveBeenCalled();
  });

  it("defaults upper_threshold to null when omitted on an anomaly `event`", async () => {
    fetchMock.mockResolvedValueOnce({ items: [] });
    useAnomalyStore.setState({
      items: [{ bucket_start_ns: 0n, max_score: null, avg_score: null, event_count: 0, upper_threshold: null, alert_count: 0 }],
      source: null,
      knownSources: new Set(),
      resolution: "1m",
    });
    const spy = vi.spyOn(useAnomalyStore.getState(), "appendScore");

    render(<WsProvider><AlertFeed /></WsProvider>);
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    act(() => { MockWS.last!._open(); });
    await new Promise(r => setTimeout(r, 0));

    act(() => {
      MockWS.last!._msg({ type: "event", data: {
        event_id: "e3", timestamp_ns: "7", observed_ns: "7",
        severity_id: 3, severity_text: "MEDIUM", source_type: "kafka",
        message: "anom", template_id: 1, entity_refs: [], entity_summary: {},
        score: 0.7,  // no upper_threshold
      } });
    });
    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(spy).toHaveBeenCalledWith(expect.objectContaining({
      upper_threshold: null,
      source_type: "kafka",
    }));
  });
});
