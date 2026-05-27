import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import { EventStream } from "./EventStream";
import { WsProvider } from "@/components/WsProvider";
import { useEventStore, MAX_EVENTS } from "@/stores/events";
import * as wsBus from "@/lib/wsBus";
import { _resetForTests } from "@/lib/wsFilter";
import { api } from "@/lib/api";
import type { LiveEvent } from "@/lib/types";
import { applySchemaValidation } from "@/test/helpers/apiMock";

vi.mock("@/lib/api", async () => {
  const { createApiMock } = await import("@/test/helpers/apiMock");
  return createApiMock({
    defaultGetResponse: { items: [], total: 0, page: 1, limit: 100, has_next: false },
  });
});

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
  wsBus._clearAllForTests();
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

  it("store filter change re-filters the visible stream (no UI filter bar — S-335)", async () => {
    // The legacy source-chip / min-severity bar was removed in S-335; the store
    // filter machinery stays and still drives the locally-visible subset. Drive
    // the filter via the store and assert the non-matching row drops out.
    renderWithProvider();
    act(() => useEventStore.getState().ingest([ev(1, { source_type: "auth" }), ev(2, { source_type: "syslog" })]));
    await waitFor(() => expect(screen.getByText("m1")).toBeInTheDocument());
    act(() => {
      useEventStore.setState({
        filter: { sources: new Set(["auth"]), minSeverity: 0, templateIds: new Set() },
      });
    });
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

  it("outer section is a flush flex column (h-full min-h-0) with NO card chrome — S-335", async () => {
    const { container } = renderWithProvider();
    await waitFor(() => expect(MockWS.last).not.toBeNull());
    const section = container.querySelector("section");
    expect(section).not.toBeNull();
    const cls = section!.className;
    expect(cls).toContain("flex");
    expect(cls).toContain("flex-col");
    expect(cls).toContain("h-full");
    expect(cls).toContain("min-h-0");
    expect(cls).not.toContain("min-h-[320px]");
    expect(cls).not.toContain("h-[420px]");
    // S-335: flush full-bleed — no card wrapper (rounded / border / bg-card).
    expect(cls).not.toContain("rounded");
    expect(cls).not.toContain("border");
    expect(cls).not.toContain("bg-card");
  });

  it("does NOT render the legacy source / min-severity filter bar — S-335", async () => {
    renderWithProvider();
    await waitFor(() => expect(screen.getByTestId("query-field")).toBeInTheDocument());
    // The filter bar's controls are gone; only the query field expresses filtering now.
    expect(screen.queryByLabelText(/min severity/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/template id/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^sources:$/)).not.toBeInTheDocument();
  });

  // ── S-331: single controlled query field in the toolbar ──────────────────

  it("uncontrolled query field keeps the jq · sigma · sql hint + placeholder", async () => {
    renderWithProvider();
    await waitFor(() => expect(screen.getByTestId("query-field")).toBeInTheDocument());
    expect(screen.getByText(/jq · sigma · sql/i)).toBeInTheDocument();
    const input = screen.getByTestId("event-query-field") as HTMLInputElement;
    expect(input.placeholder).toMatch(/query events/i);
  });

  it("controlled query field reflects the query prop and fires onQueryChange", async () => {
    const onQueryChange = vi.fn();
    render(
      <WsProvider>
        <EventStream query="auth denied" onQueryChange={onQueryChange} />
      </WsProvider>,
    );
    const input = await waitFor(
      () => screen.getByTestId("event-query-field") as HTMLInputElement,
    );
    expect(input.value).toBe("auth denied");
    fireEvent.change(input, { target: { value: "disk" } });
    expect(onQueryChange).toHaveBeenCalledWith("disk");
  });

  it("renders the matched subset (matched-results) when queryActive", async () => {
    render(
      <WsProvider>
        <EventStream
          query="m1"
          onQueryChange={vi.fn()}
          queryActive
          filteredEvents={[ev(1)]}
          matchCount={1}
        />
      </WsProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("matched-results")).toBeInTheDocument());
    expect(screen.getByText("m1")).toBeInTheDocument();
    expect(screen.getByTestId("event-match-count")).toHaveTextContent("1");
  });

  it("shows the empty-match message when queryActive with no filtered events", async () => {
    render(
      <WsProvider>
        <EventStream
          query="zzz"
          onQueryChange={vi.fn()}
          queryActive
          filteredEvents={[]}
          matchCount={0}
        />
      </WsProvider>,
    );
    await waitFor(() =>
      expect(screen.getByText(/no events match the current query/i)).toBeInTheDocument(),
    );
    expect(screen.getByTestId("event-match-count")).toHaveTextContent("0");
  });

  it("renders the non-blocking validity hint when queryValid is false", async () => {
    render(
      <WsProvider>
        <EventStream
          query="nope: value"
          onQueryChange={vi.fn()}
          queryValid={false}
          queryHint="Unknown field: nope"
        />
      </WsProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("query-hint")).toBeInTheDocument());
    expect(screen.getByTestId("query-hint")).toHaveTextContent(/unknown field: nope/i);
  });

  it("surfaces parent-supplied crit/warn counts in the toolbar when controlled", async () => {
    render(
      <WsProvider>
        <EventStream
          query="error"
          onQueryChange={vi.fn()}
          queryActive
          filteredEvents={[ev(1, { severity_id: 4 })]}
          matchCount={1}
          critCount={0}
          warnCount={1}
        />
      </WsProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("events-crit-count")).toBeInTheDocument());
    expect(screen.getByTestId("events-crit-count")).toHaveTextContent("0");
    expect(screen.getByTestId("events-warn-count")).toHaveTextContent("1");
  });
});

describe("S-191 T10: REST warm-up schema validation", () => {
  beforeEach(async () => {
    _resetForTests();
    wsBus._clearAllForTests();
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
    (api.get as ReturnType<typeof vi.fn>).mockImplementationOnce(async (path, opts) =>
      applySchemaValidation({ items: [validFixture, invalidFixture] }, path, opts),
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
