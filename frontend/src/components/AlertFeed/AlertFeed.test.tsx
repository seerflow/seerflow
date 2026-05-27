import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act, fireEvent } from "@testing-library/react";
import { AlertFeed } from "./AlertFeed";
import { WsProvider } from "@/components/WsProvider";
import { useAlertStore } from "@/stores/alerts";
import { logger } from "@/lib/logger";
import * as wsBus from "@/lib/wsBus";
import type { Alert, LiveEvent } from "@/lib/types";
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

const baseAlert = (over: Partial<Record<string, unknown>> = {}): Record<string, unknown> => ({
  alert_id: "a", timestamp_ns: "1", alert_type: "ml", rule_name: "r",
  severity: 5, risk_score: 0.1, entity_uuid: null, entity_type: null,
  entity_value: null, message: "", mitre_tactics: [], mitre_techniques: [],
  dedup_count: 1, source_type: "syslog", ...over,
});

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
      { ...baseAlert({ alert_id: "warm", timestamp_ns: 1n, rule_name: "warmup-rule" }) },
    ] });
    renderWithProvider();
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    // "All" tab so derived workflow status never hides an ingested row.
    fireEvent.click(screen.getByRole("tab", { name: /All/ }));
    await waitFor(() => expect(screen.getByText("warmup-rule")).toBeInTheDocument());
    act(() => {
      MockWS.last!._open();
      MockWS.last!._msg({ type: "alert", data: baseAlert({ alert_id: "live", timestamp_ns: "2", alert_type: "sigma", rule_name: "live-rule", severity: 6, risk_score: 0.9 }) });
    });
    expect(screen.getByText("live-rule")).toBeInTheDocument();
  });

  it("buffers WS messages until warm-up resolves, then replays them (S-194 AC-3)", async () => {
    let resolveWarmup: (value: { items: unknown[] }) => void = () => {};
    const warmupPromise = new Promise<{ items: unknown[] }>(r => { resolveWarmup = r; });
    fetchMock.mockReturnValueOnce(warmupPromise);

    renderWithProvider();

    await waitFor(() => expect(MockWS.last).not.toBeNull());
    fireEvent.click(screen.getByRole("tab", { name: /All/ }));
    act(() => {
      MockWS.last!._open();
      MockWS.last!._msg({ type: "alert", data: baseAlert({ alert_id: "live", timestamp_ns: "2", alert_type: "sigma", rule_name: "live-rule", severity: 6, risk_score: 0.9 }) });
    });

    expect(screen.queryByText("live-rule")).toBeNull();

    await act(async () => {
      resolveWarmup({ items: [ baseAlert({ alert_id: "warm", timestamp_ns: 1n, rule_name: "warmup-rule" }) ] });
      await warmupPromise;
    });

    await waitFor(() => expect(screen.getByText("live-rule")).toBeInTheDocument());
    expect(screen.getByText("warmup-rule")).toBeInTheDocument();
  });

  it("resets warmedUp on unmount so a remount re-buffers WS frames (S-194 AC-3 regression)", async () => {
    fetchMock.mockResolvedValueOnce({ items: [] });
    const { unmount } = renderWithProvider();
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    act(() => { MockWS.last!._open(); });
    await new Promise(r => setTimeout(r, 0));
    unmount();

    let resolveWarmup: (v: { items: unknown[] }) => void = () => {};
    const warmupPromise = new Promise<{ items: unknown[] }>(r => { resolveWarmup = r; });
    fetchMock.mockReturnValueOnce(warmupPromise);
    useAlertStore.setState({ alerts: [], detail: {}, filter: { severities: new Set(), types: new Set(), sources: new Set(), tactics: new Set() }, dropped: 0, selectedAlertId: null });
    wsBus._clearAllForTests();

    renderWithProvider();
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    act(() => {
      MockWS.last!._open();
      MockWS.last!._msg({ type: "alert", data: baseAlert({ alert_id: "remounted", timestamp_ns: "1", rule_name: "remount-rule" }) });
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

    await act(async () => {
      for (let i = 0; i < 250; i++) {
        MockWS.last!._msg({ type: "alert", data: baseAlert({ alert_id: `a${i}`, timestamp_ns: String(i + 1), rule_name: `r${i}` }) });
      }
    });

    expect(warn).toHaveBeenCalled();

    await act(async () => { resolveWarmup({ items: [] }); await warmupPromise; });
    await waitFor(() => {
      expect(useAlertStore.getState().alerts.length).toBeLessThanOrEqual(200);
    });
  });

  it("subscribes to wsBus __status so connection lifecycle updates the alert store status", async () => {
    fetchMock.mockResolvedValueOnce({ items: [] });
    renderWithProvider();
    await waitFor(() => expect(MockWS.last).not.toBeNull());

    act(() => { MockWS.last!._open(); });
    await waitFor(() => expect(useAlertStore.getState().status).toBe("open"));

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

    act(() => {
      useAlertStore.setState({
        filter: { severities: new Set(["critical"]), types: new Set(), sources: new Set(), tactics: new Set() },
      });
    });
    expect(MockWS.last!.sent).toEqual([]);
    await act(async () => { await vi.advanceTimersByTimeAsync(200); });
    const filterFrames = MockWS.last!.sent.filter(
      (m): m is { type: string; min_severity?: number } =>
        typeof m === "object" && m !== null && (m as { type?: unknown }).type === "filter",
    );
    expect(filterFrames.some(m => m.min_severity === 5)).toBe(true);
    vi.useRealTimers();
  });

  it("does not ingest alerts arriving under type:'batch' (alerts ship via alert_batch)", async () => {
    fetchMock.mockResolvedValueOnce({ items: [] });
    renderWithProvider();
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    act(() => { MockWS.last!._open(); });
    await new Promise(r => setTimeout(r, 0));

    const ghost = { ...baseAlert({ alert_id: "ghost-1", timestamp_ns: 1n, rule_name: "ghost-rule" }) };
    act(() => {
      wsBus.emit({ type: "batch", events: [ghost] as unknown as LiveEvent[] });
    });

    expect(screen.queryByText("ghost-rule")).toBeNull();
  });

  it("handles alert_batch arrivals", async () => {
    fetchMock.mockResolvedValueOnce({ items: [] });
    renderWithProvider();
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    fireEvent.click(screen.getByRole("tab", { name: /All/ }));
    act(() => { MockWS.last!._open(); });

    act(() => {
      MockWS.last!._msg({ type: "alert_batch", alerts: [
        baseAlert({ alert_id: "b1", timestamp_ns: "1", rule_name: "batch-rule-1" }),
        baseAlert({ alert_id: "b2", timestamp_ns: "2", rule_name: "batch-rule-2" }),
      ] });
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

  // ── S-336 SOC-console structure ───────────────────────────────────────────

  it("renders the KPI header with title, sub-label and summary stats", async () => {
    fetchMock.mockResolvedValueOnce({ items: [] });
    renderWithProvider();
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    expect(screen.getByRole("heading", { name: "Alerts" })).toBeInTheDocument();
    expect(screen.getByText(/last 24h · auto-refresh 5s/)).toBeInTheDocument();
    // Demo KPI values are always present.
    expect(screen.getByText("38s")).toBeInTheDocument();
    expect(screen.getByText("14m")).toBeInTheDocument();
    expect(screen.getByText("3.2%")).toBeInTheDocument();
  });

  it("renders the header action buttons (demo stubs)", async () => {
    fetchMock.mockResolvedValueOnce({ items: [] });
    renderWithProvider();
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    expect(screen.getByRole("button", { name: "Export ndjson" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Suppression rules" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "+ New rule" })).toBeInTheDocument();
  });

  it("renders the status tabs and filter chips", async () => {
    fetchMock.mockResolvedValueOnce({ items: [] });
    renderWithProvider();
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    expect(screen.getByRole("tab", { name: /Open/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Suppressed/ })).toBeInTheDocument();
    expect(screen.getByText("severity")).toBeInTheDocument();
    expect(screen.getByText("detector")).toBeInTheDocument();
  });

  it("renders the alert volume strip and the 8-column table header", async () => {
    fetchMock.mockResolvedValueOnce({ items: [] });
    renderWithProvider();
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    expect(screen.getByTestId("alert-volume-strip")).toBeInTheDocument();
    expect(screen.getByText("Sev · Score")).toBeInTheDocument();
    expect(screen.getByText("Entities")).toBeInTheDocument();
    expect(screen.getByText("Owner")).toBeInTheDocument();
  });

  it("navigates to #/alerts/:id on row click instead of opening an inline panel", async () => {
    fetchMock.mockResolvedValueOnce({ items: [
      baseAlert({ alert_id: "nav-target", timestamp_ns: 5n, rule_name: "nav-rule", severity: 6 }),
    ] });
    renderWithProvider();
    // Land on the "All" tab so derived status never hides the row.
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    fireEvent.click(screen.getByRole("tab", { name: /All/ }));
    await waitFor(() => expect(screen.getByText("nav-rule")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /alert nav-rule/ }));
    expect(window.location.hash).toBe("#/alerts/nav-target");
  });

  it("does not render an inline detail panel or feedback controls", async () => {
    fetchMock.mockResolvedValueOnce({ items: [
      baseAlert({ alert_id: "x1", timestamp_ns: 5n, rule_name: "x-rule", severity: 6 }),
    ] });
    renderWithProvider();
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    fireEvent.click(screen.getByRole("tab", { name: /All/ }));
    await waitFor(() => expect(screen.getByText("x-rule")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /alert x-rule/ }));
    expect(screen.queryByRole("button", { name: /true positive/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("feedback history")).not.toBeInTheDocument();
  });

  it("paginates client-side over the loaded set and changes rows-per-page", async () => {
    const items = Array.from({ length: 30 }, (_, i) =>
      baseAlert({ alert_id: `p-${i}`, timestamp_ns: BigInt(100 - i), rule_name: `rule-${i}`, severity: 6 }),
    );
    fetchMock.mockResolvedValueOnce({ items });
    renderWithProvider();
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    // "All" tab shows every loaded alert regardless of derived status.
    fireEvent.click(screen.getByRole("tab", { name: /All/ }));
    await waitFor(() => expect(screen.getByText("rule-0")).toBeInTheDocument());
    // Default 25 rows/page: rule-0..rule-24 visible, rule-25 not.
    expect(screen.queryByText("rule-25")).not.toBeInTheDocument();
    expect(screen.getByTestId("alerts-page-summary")).toHaveTextContent("of 30");

    // Bump to 50 rows/page → all 30 visible.
    fireEvent.click(screen.getByRole("button", { name: "50" }));
    await waitFor(() => expect(screen.getByText("rule-25")).toBeInTheDocument());
  });

  it("empty state renders with no rows", async () => {
    fetchMock.mockResolvedValueOnce({ items: [] });
    renderWithProvider();
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    expect(screen.queryByRole("button", { name: /^alert / })).not.toBeInTheDocument();
    expect(screen.getByTestId("alerts-page-summary")).toHaveTextContent("of 0");
  });

  it("active tab filters rows by derived status", async () => {
    // Mix of critical (mostly open/triaging) and low (resolved) alerts.
    const items: Record<string, unknown>[] = [
      baseAlert({ alert_id: "crit-a", timestamp_ns: 9n, rule_name: "crit-rule", severity: 6 }),
      baseAlert({ alert_id: "low-a", timestamp_ns: 8n, rule_name: "low-rule", severity: 1 }),
    ];
    fetchMock.mockResolvedValueOnce({ items });
    renderWithProvider();
    await waitFor(() => expect(screen.getByText("crit-rule")).toBeInTheDocument());

    // Low-severity alerts resolve; click Resolved tab → low-rule stays, crit-rule may hide.
    fireEvent.click(screen.getByRole("tab", { name: /Resolved/ }));
    await waitFor(() => expect(screen.getByText("low-rule")).toBeInTheDocument());
  });
});

describe("S-191 T9: REST warm-up schema validation", () => {
  beforeEach(() => {
    vi.stubGlobal("WebSocket", MockWS as unknown as typeof WebSocket);
    fetchMock.mockReset();
    MockWS.last = null;
    wsBus._clearAllForTests();
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
    const validFixture = baseAlert({ alert_id: "valid", timestamp_ns: 1n, rule_name: "valid-rule" }) as unknown as Alert;
    const invalidFixture = { ...validFixture, alert_id: "bad", severity: 999 };
    fetchMock.mockResolvedValueOnce({ items: [validFixture, invalidFixture] });

    expect(validateOrDropItem(AlertSchema, invalidFixture, "rest:test")).toBeNull();

    render(<WsProvider><AlertFeed /></WsProvider>);
    await waitFor(() => {
      expect(useAlertStore.getState().alerts.map(a => a.alert_id)).toEqual(["valid"]);
    });
    expect(validationMetrics.getCounters()["rest:/api/v1/alerts"]).toBe(1);
  });

  it("fans anomaly-scored `event` frames out to useAnomalyStore.appendScore", async () => {
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
        event_id: "e1", timestamp_ns: "5", observed_ns: "5",
        severity_id: 3, severity_text: "MEDIUM", source_type: "syslog",
        message: "anom", template_id: 1, entity_refs: [], entity_summary: {},
        score: 0.9, is_anomaly: true, upper_threshold: 0.5,
      } });
    });
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
      } });
    });
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
        score: 0.7,
      } });
    });
    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(spy).toHaveBeenCalledWith(expect.objectContaining({
      upper_threshold: null,
      source_type: "kafka",
    }));
  });
});
