import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import { EventStream } from "./EventStream";
import { WsProvider } from "@/components/WsProvider";
import { useEventStore, MAX_EVENTS } from "@/stores/events";
import * as wsBus from "@/lib/wsBus";
import { _resetForTests } from "@/lib/wsFilter";
import { api } from "@/lib/api";
import { validateOrDropItem } from "@/lib/schemas";
import type { LiveEvent } from "@/lib/types";

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(async (path: string, opts?: { schema?: unknown; itemsKey?: string }) => {
      const res: Record<string, unknown> = { items: [], total: 0, page: 1, limit: 100, has_next: false };
      // Mimic api.ts::request: when schema+itemsKey provided, validate each
      // item with the shared `validateOrDropItem` so invalid rows are dropped
      // and `rest:<path-without-query>` counters are incremented.
      if (opts?.schema && opts?.itemsKey) {
        const kind = `rest:${path.split("?")[0]}`;
        const raw = res[opts.itemsKey];
        if (Array.isArray(raw)) {
          const items = raw
            .map(item => validateOrDropItem(opts.schema as Parameters<typeof validateOrDropItem>[0], item, kind))
            .filter((x): x is NonNullable<typeof x> => x !== null);
          return { ...res, [opts.itemsKey]: items };
        }
      }
      return res;
    }),
    post: vi.fn(),
  },
  ApiError: class ApiError extends Error {},
}));

function ev(i: number, over: Partial<LiveEvent> = {}): LiveEvent {
  return {
    event_id: `e${i}`, timestamp_ns: BigInt(i), observed_ns: BigInt(i),
    severity_id: 2, severity_text: "INFO", source_type: "syslog",
    message: `m${i}`, template_id: 1, entity_refs: [], entity_summary: {},
    ...over,
  };
}

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
  return render(<WsProvider><EventStream /></WsProvider>);
}

beforeEach(() => {
  _resetForTests();
  wsBus.clearAll();
  MockWS.last = null;
  vi.stubGlobal("WebSocket", MockWS as unknown as typeof WebSocket);
  useEventStore.setState({
    events: [], pausedBuffer: [], paused: false,
    filter: { sources: new Set(), minSeverity: 0, templateIds: new Set() },
    knownSources: new Set(), status: "open",
    droppedFromRing: 0, droppedFromPausedBuffer: 0, lastDisconnectedAtMs: null,
  });
});

afterEach(() => vi.unstubAllGlobals());

describe("EventStream", () => {
  it("renders empty state when store is empty + status=open", async () => {
    renderWithProvider();
    await waitFor(() => expect(screen.getByText(/waiting for the pipeline/i)).toBeInTheDocument());
  });

  it("renders event rows when store has events", async () => {
    renderWithProvider();
    act(() => useEventStore.getState().ingest([ev(1), ev(2)]));
    await waitFor(() => expect(screen.getByText("m2")).toBeInTheDocument());
    expect(screen.getByText("m1")).toBeInTheDocument();
  });

  it("clicking pause halts visible appends, resume catches up", async () => {
    renderWithProvider();
    act(() => useEventStore.getState().ingest([ev(1)]));
    await waitFor(() => expect(screen.getByText("m1")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /pause/i }));
    act(() => useEventStore.getState().ingest([ev(2), ev(3)]));
    expect(screen.queryByText("m3")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /resume.*2 buffered/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /resume/i }));
    await waitFor(() => expect(screen.getByText("m3")).toBeInTheDocument());
  });

  it("source chip click triggers wsFilter intent + local re-filter", async () => {
    renderWithProvider();
    act(() => useEventStore.getState().ingest([ev(1, { source_type: "auth" }), ev(2, { source_type: "syslog" })]));
    await waitFor(() => expect(screen.getByText("m1")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "auth" }));
    await waitFor(() => expect(screen.queryByText("m2")).not.toBeInTheDocument());
    expect(screen.getByText("m1")).toBeInTheDocument();
  });

  it("ring cap honored on heavy ingest", () => {
    const big = Array.from({ length: MAX_EVENTS + 50 }, (_, i) => ev(i));
    act(() => useEventStore.getState().ingest(big));
    expect(useEventStore.getState().events.length).toBe(MAX_EVENTS);
  });

  it("ingests LiveEvent frames from wsBus 'event' emission once (no double-write)", async () => {
    renderWithProvider();
    await waitFor(() => expect(screen.getByText(/waiting for the pipeline/i)).toBeInTheDocument());
    const e = ev(42);
    act(() => { wsBus.emit({ type: "event", data: e }); });
    // One ingest → events list contains exactly that one LiveEvent.
    await waitFor(() => expect(screen.getByText("m42")).toBeInTheDocument());
    expect(useEventStore.getState().events).toHaveLength(1);
  });

  it("ingests LiveEvents from wsBus 'batch' emission when first item has event_id", async () => {
    renderWithProvider();
    await waitFor(() => expect(screen.getByText(/waiting for the pipeline/i)).toBeInTheDocument());
    act(() => { wsBus.emit({ type: "batch", events: [ev(1), ev(2)] }); });
    await waitFor(() => expect(screen.getByText("m2")).toBeInTheDocument());
    expect(screen.getByText("m1")).toBeInTheDocument();
  });

  it("ignores wsBus 'batch' when first item is not a LiveEvent", async () => {
    renderWithProvider();
    await waitFor(() => expect(screen.getByText(/waiting for the pipeline/i)).toBeInTheDocument());
    // Alerts-batch shape has no event_id on the first item.
    const alertLike = { alert_id: "a1", timestamp_ns: 1n } as unknown as LiveEvent;
    act(() => { wsBus.emit({ type: "batch", events: [alertLike] }); });
    // Store stays empty — EventStream did not ingest the alert batch.
    expect(useEventStore.getState().events).toHaveLength(0);
  });

  it("status pip mirrors wsBus __status updates", async () => {
    renderWithProvider();
    // Initial render shows the connecting pip.
    const dot = await waitFor(() => screen.getByLabelText(/WebSocket status:/i));
    expect(dot.getAttribute("aria-label")).toBe("WebSocket status: connecting");
    act(() => { wsBus.emit({ type: "__status", status: "open" }); });
    await waitFor(() => {
      expect(screen.getByLabelText("WebSocket status: open")).toBeInTheDocument();
    });
    act(() => { wsBus.emit({ type: "__status", status: "closed" }); });
    await waitFor(() => {
      expect(screen.getByLabelText("WebSocket status: closed")).toBeInTheDocument();
    });
  });

  it("pushes merged filter payload via useWsSend after 150 ms debounce when filter changes", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderWithProvider();
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    act(() => { MockWS.last!._open(); });
    MockWS.last!.sent.length = 0;

    act(() => {
      useEventStore.setState({
        filter: { sources: new Set(["auth"]), minSeverity: 0, templateIds: new Set() },
      });
    });
    // Before debounce expires, nothing sent yet.
    expect(MockWS.last!.sent).toEqual([]);
    await act(async () => { await vi.advanceTimersByTimeAsync(200); });
    const filterFrames = MockWS.last!.sent.filter(
      (m): m is { type: string; sources?: string[] } =>
        typeof m === "object" && m !== null && (m as { type?: unknown }).type === "filter",
    );
    expect(filterFrames.some(m => Array.isArray(m.sources) && m.sources.includes("auth"))).toBe(true);
    vi.useRealTimers();
  });

  it("does NOT dispatch the legacy seerflow:wsfilter-changed CustomEvent", async () => {
    renderWithProvider();
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    const listener = vi.fn();
    window.addEventListener("seerflow:wsfilter-changed", listener);
    try {
      act(() => {
        useEventStore.setState({
          filter: { sources: new Set(["auth"]), minSeverity: 0, templateIds: new Set() },
        });
      });
      // Allow the 150 ms debounce to elapse.
      await new Promise(r => setTimeout(r, 200));
      expect(listener).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener("seerflow:wsfilter-changed", listener);
    }
  });

  it("does NOT render the internal disconnected banner — DisconnectedBanner handles it globally now", async () => {
    renderWithProvider();
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    act(() => { wsBus.emit({ type: "__status", status: "closed" }); });
    // The legacy internal banner text must not appear from the EventStream component.
    // (The global <DisconnectedBanner /> is NOT mounted by this test harness, so no
    //  "disconnected" text at all.)
    await new Promise(r => setTimeout(r, 50));
    expect(screen.queryByText(/disconnected/i)).not.toBeInTheDocument();
  });

  it("outer section uses h-full min-h-0 (grid cell fill) without legacy min-h-[320px] or h-[420px]", async () => {
    const { container } = renderWithProvider();
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    const section = container.querySelector("section");
    expect(section).not.toBeNull();
    const cls = section!.className;
    expect(cls).toContain("h-full");
    expect(cls).toContain("min-h-0");
    expect(cls).not.toContain("min-h-[320px]");
    expect(cls).not.toContain("h-[420px]");
  });
});

describe("S-191 T10: REST warm-up schema validation", () => {
  beforeEach(async () => {
    _resetForTests();
    wsBus.clearAll();
    MockWS.last = null;
    vi.stubGlobal("WebSocket", MockWS as unknown as typeof WebSocket);
    useEventStore.setState({
      events: [], pausedBuffer: [], paused: false,
      filter: { sources: new Set(), minSeverity: 0, templateIds: new Set() },
      knownSources: new Set(), status: "open",
      droppedFromRing: 0, droppedFromPausedBuffer: 0, lastDisconnectedAtMs: null,
    });
    const metrics = await import("@/lib/validationMetrics");
    metrics._resetForTests();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("drops invalid REST items from /api/v1/events warm-up under rest:/api/v1/events", async () => {
    const validFixture: LiveEvent = {
      event_id: "e1", timestamp_ns: 1n, observed_ns: 1n,
      severity_id: 2, severity_text: "INFO", source_type: "syslog",
      message: "m1", template_id: 1, entity_refs: [], entity_summary: {},
    };
    // severity_id 999 fails LiveEventSchema (OCSF 0..6).
    const invalidFixture = { ...validFixture, event_id: "bad", severity_id: 999 };
    (api.get as ReturnType<typeof vi.fn>).mockImplementationOnce(
      async (path: string, opts?: { schema?: unknown; itemsKey?: string }) => {
        const res: Record<string, unknown> = { items: [validFixture, invalidFixture] };
        if (opts?.schema && opts?.itemsKey) {
          const kind = `rest:${path.split("?")[0]}`;
          const raw = res[opts.itemsKey];
          if (Array.isArray(raw)) {
            const items = raw
              .map(item => validateOrDropItem(opts.schema as Parameters<typeof validateOrDropItem>[0], item, kind))
              .filter((x): x is NonNullable<typeof x> => x !== null);
            res[opts.itemsKey] = items;
          }
        }
        return res;
      },
    );

    render(<WsProvider><EventStream /></WsProvider>);
    // Warm-up resolves asynchronously → wait for the store to land exactly the
    // valid event; the invalid one must be dropped via rest:/api/v1/events.
    await waitFor(() => {
      expect(useEventStore.getState().events.map(e => e.event_id)).toEqual(["e1"]);
    });
    const metrics = await import("@/lib/validationMetrics");
    expect(metrics.getCounters()["rest:/api/v1/events"]).toBe(1);
  });
});
