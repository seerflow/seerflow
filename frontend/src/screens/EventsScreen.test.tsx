/**
 * EventsScreen unit tests — S-325.
 * Covers layout, toolbar, inspector integration, volume strip, and column headers.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";
import { EventsScreen } from "./EventsScreen";
import { WsProvider } from "@/components/WsProvider";
import { useEventStore } from "@/stores/events";
import * as wsBus from "@/lib/wsBus";
import { _resetForTests } from "@/lib/wsFilter";
import type { LiveEvent } from "@/lib/types";

// Mock API (same pattern as EventStream.test.tsx)
vi.mock("@/lib/api", async () => {
  const { createApiMock } = await import("@/test/helpers/apiMock");
  return createApiMock({
    defaultGetResponse: { items: [], total: 0, page: 1, limit: 100, has_next: false },
  });
});

// Mock MiniVolume (uPlot doesn't work in jsdom)
vi.mock("@/viz/MiniVolume", () => ({
  MiniVolume: () => <div data-testid="mini-volume" />,
}));

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

function ev(i: number, over: Partial<LiveEvent> = {}): LiveEvent {
  return {
    event_id: `e${i}`, timestamp_ns: BigInt(i), observed_ns: BigInt(i),
    severity_id: 2, severity_text: "INFO", source_type: "syslog",
    message: `msg${i}`, template_id: 1, entity_refs: [], entity_summary: {},
    ...over,
  };
}

function renderScreen(): ReturnType<typeof render> {
  return render(<WsProvider><EventsScreen /></WsProvider>);
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

describe("EventsScreen", () => {
  it("mounts without crashing", async () => {
    renderScreen();
    await waitFor(() => expect(screen.getByTestId("events-screen")).toBeInTheDocument());
  });

  it("renders EventStream inside the layout", async () => {
    renderScreen();
    // EventStream renders the empty state text when no events
    await waitFor(() => expect(screen.getByText(/waiting for the pipeline/i)).toBeInTheDocument());
  });

  it("shows inspector placeholder before any event is selected", async () => {
    renderScreen();
    await waitFor(() => expect(screen.getByText(/select an event to inspect/i)).toBeInTheDocument());
  });

  it("uses 1fr 320px grid layout", async () => {
    const { container } = renderScreen();
    await waitFor(() => expect(screen.getByTestId("events-screen")).toBeInTheDocument());
    const root = container.querySelector("[data-testid='events-screen']") as HTMLElement;
    expect(root.style.gridTemplateColumns).toBe("1fr 320px");
  });

  it("shows inspector details when an event row is clicked", async () => {
    renderScreen();
    await waitFor(() => expect(screen.getByText(/waiting for the pipeline/i)).toBeInTheDocument());

    const errorEvent = ev(1, {
      severity_id: 5,
      severity_text: "ERROR",
      message: "inspector_test_msg",
    });
    act(() => useEventStore.getState().ingest([errorEvent]));
    await waitFor(() => expect(screen.getAllByRole("button", { name: /event row/i }).length).toBeGreaterThan(0));

    const rows = screen.getAllByRole("button", { name: /event row/i });
    fireEvent.click(rows[0]);

    await waitFor(() =>
      expect(screen.getByTestId("inspector-severity")).toHaveTextContent("ERROR"),
    );
  });

  it("shows volume strip label", async () => {
    renderScreen();
    await waitFor(() => expect(screen.getByText(/volume · 60s window/i)).toBeInTheDocument());
  });

  it("shows all six column headers", async () => {
    renderScreen();
    for (const col of ["timestamp", "level", "source", "host", "logger", "message"]) {
      await waitFor(() => expect(screen.getByText(col, { exact: true })).toBeInTheDocument());
    }
  });

  it("shows Pause button in the toolbar", async () => {
    renderScreen();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /pause/i })).toBeInTheDocument(),
    );
  });

  it("shows Export button in the toolbar", async () => {
    renderScreen();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /export/i })).toBeInTheDocument(),
    );
  });

  it("shows query field with jq · sigma · sql hint", async () => {
    renderScreen();
    await waitFor(() => expect(screen.getByTestId("query-field")).toBeInTheDocument());
    expect(screen.getByText(/jq · sigma · sql/i)).toBeInTheDocument();
  });
});
