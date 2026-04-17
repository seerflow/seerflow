import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import { EventStream } from "./EventStream";
import { useEventStore, MAX_EVENTS } from "@/stores/events";
import { _resetForTests } from "@/lib/wsFilter";
import type { LiveEvent } from "@/lib/types";

function ev(i: number, over: Partial<LiveEvent> = {}): LiveEvent {
  return {
    event_id: `e${i}`, timestamp_ns: BigInt(i), observed_ns: BigInt(i),
    severity_id: 2, severity_text: "INFO", source_type: "syslog",
    message: `m${i}`, template_id: 1, entity_refs: [], entity_summary: {},
    ...over,
  };
}

beforeEach(() => {
  _resetForTests();
  useEventStore.setState({
    events: [], pausedBuffer: [], paused: false,
    filter: { sources: new Set(), minSeverity: 0, templateIds: new Set() },
    knownSources: new Set(), status: "open",
    droppedFromRing: 0, droppedFromPausedBuffer: 0, lastDisconnectedAtMs: null,
  });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: true, status: 200,
    text: async () => JSON.stringify({ items: [], total: 0, page: 1, limit: 100, has_next: false }),
    headers: { get: () => "application/json" },
  }));
});

afterEach(() => vi.unstubAllGlobals());

describe("EventStream", () => {
  it("renders empty state when store is empty + status=open", async () => {
    render(<EventStream />);
    await waitFor(() => expect(screen.getByText(/waiting for the pipeline/i)).toBeInTheDocument());
  });

  it("renders event rows when store has events", async () => {
    render(<EventStream />);
    act(() => useEventStore.getState().ingest([ev(1), ev(2)]));
    await waitFor(() => expect(screen.getByText("m2")).toBeInTheDocument());
    expect(screen.getByText("m1")).toBeInTheDocument();
  });

  it("clicking pause halts visible appends, resume catches up", async () => {
    render(<EventStream />);
    act(() => useEventStore.getState().ingest([ev(1)]));
    await waitFor(() => expect(screen.getByText("m1")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /pause/i }));
    act(() => useEventStore.getState().ingest([ev(2), ev(3)]));
    expect(screen.queryByText("m3")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /resume.*2 buffered/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /resume/i }));
    await waitFor(() => expect(screen.getByText("m3")).toBeInTheDocument());
  });

  it("disconnected banner appears after 3s of closed status", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<EventStream />);
    act(() => useEventStore.getState().setStatus("closed"));
    await act(async () => { await vi.advanceTimersByTimeAsync(3500); });
    await waitFor(() => expect(screen.getByText(/disconnected/i)).toBeInTheDocument());
    vi.useRealTimers();
  });

  it("source chip click triggers wsFilter intent + local re-filter", async () => {
    render(<EventStream />);
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
});
