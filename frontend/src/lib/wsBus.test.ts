import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import * as bus from "./wsBus";
import type { WsMessage } from "./types";
import { logger } from "@/lib/logger";

const statusMsg: WsMessage = {
  type: "status",
  data: {
    events_ingested_per_sec: 1,
    alerts_24h: 0,
    connected_clients: 1,
    dropped_events: 0,
    dropped_alerts: 0,
    dropped_total: 0,
  },
};

const eventMsg: WsMessage = {
  type: "event",
  data: {
    event_id: "evt-1",
    timestamp_ns: 1000n,
    observed_ns: 1001n,
    severity_id: 3,
    severity_text: "INFO",
    source_type: "syslog",
    message: "m",
    template_id: 7,
    entity_refs: [],
  },
};

beforeEach(() => {
  bus._clearAllForTests();
  bus._resetFrameBufferForTests();
});

describe("wsBus", () => {
  it("delivers a matching emit to a subscriber", () => {
    const fn = vi.fn();
    bus.on("status", fn);
    bus.emit(statusMsg);
    expect(fn).toHaveBeenCalledTimes(1);
    expect(fn).toHaveBeenCalledWith(statusMsg);
  });

  it("ignores emits of a different type", () => {
    const fn = vi.fn();
    bus.on("alert", fn);
    bus.emit(statusMsg);
    expect(fn).not.toHaveBeenCalled();
  });

  it("fans out to every subscriber of the same type", () => {
    const a = vi.fn();
    const b = vi.fn();
    bus.on("status", a);
    bus.on("status", b);
    bus.emit(statusMsg);
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(1);
  });

  it("returns an unsubscribe that removes the handler", () => {
    const fn = vi.fn();
    const off = bus.on("status", fn);
    off();
    bus.emit(statusMsg);
    expect(fn).not.toHaveBeenCalled();
  });

  it("isolates handler exceptions so others still receive the emit", () => {
    const bad = vi.fn(() => { throw new Error("boom"); });
    const good = vi.fn();
    bus.on("status", bad);
    bus.on("status", good);
    bus.emit(statusMsg);
    expect(bad).toHaveBeenCalledTimes(1);
    expect(good).toHaveBeenCalledTimes(1);
  });

  it("is a no-op after clearAll with no handlers", () => {
    expect(() => bus.emit(statusMsg)).not.toThrow();
  });
});

describe("_clearAllForTests (S-208)", () => {
  it("on() → _clearAllForTests() → off() is a no-op", () => {
    const spy = vi.fn();
    const off = bus.on("alert", spy);
    bus._clearAllForTests();
    expect(() => off()).not.toThrow();
    bus.emit({
      type: "alert",
      data: {
        alert_id: "a-1",
        timestamp_ns: 1n,
        alert_type: "ml",
        rule_name: "r",
        severity: 3,
        risk_score: 0.5,
        entity_uuid: null,
        entity_type: null,
        entity_value: null,
        message: "m",
        mitre_tactics: [],
        mitre_techniques: [],
        dedup_count: 0,
      },
    });
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("emitCoalesced (S-209)", () => {
  beforeEach(() => {
    bus._clearAllForTests();
    bus._resetFrameBufferForTests();
    vi.useFakeTimers();
    vi.stubGlobal("requestAnimationFrame", (fn: FrameRequestCallback) => {
      setTimeout(() => fn(performance.now()), 0);
      return 0;
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("passes non-event frames through synchronously (no rAF scheduling)", () => {
    const spy = vi.fn();
    bus.on("status", spy);

    bus.emitCoalesced(statusMsg);

    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith(statusMsg);
  });

  it("falls back to synchronous emit when requestAnimationFrame is undefined", () => {
    // The describe-block afterEach calls vi.unstubAllGlobals(), so the inner
    // stub override is cleared there; no inline unstub needed.
    vi.stubGlobal("requestAnimationFrame", undefined);
    const spy = vi.fn();
    bus.on("event", spy);

    bus.emitCoalesced(eventMsg);

    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith(eventMsg);
  });

  it("defers a single event to the next rAF tick and re-emits as type=event", async () => {
    const eventSpy = vi.fn();
    const batchSpy = vi.fn();
    bus.on("event", eventSpy);
    bus.on("batch", batchSpy);

    bus.emitCoalesced(eventMsg);

    // Not yet flushed.
    expect(eventSpy).not.toHaveBeenCalled();
    expect(batchSpy).not.toHaveBeenCalled();

    await vi.runAllTimersAsync();

    expect(eventSpy).toHaveBeenCalledTimes(1);
    expect(eventSpy).toHaveBeenCalledWith(eventMsg);
    expect(batchSpy).not.toHaveBeenCalled();
  });

  it("coalesces multiple events in one tick into a single batch frame (order preserved)", async () => {
    const eventSpy = vi.fn();
    const batchSpy = vi.fn();
    bus.on("event", eventSpy);
    bus.on("batch", batchSpy);

    const e1 = { ...eventMsg, data: { ...eventMsg.data, event_id: "evt-1" } };
    const e2 = { ...eventMsg, data: { ...eventMsg.data, event_id: "evt-2" } };
    const e3 = { ...eventMsg, data: { ...eventMsg.data, event_id: "evt-3" } };
    bus.emitCoalesced(e1);
    bus.emitCoalesced(e2);
    bus.emitCoalesced(e3);

    await vi.runAllTimersAsync();

    expect(eventSpy).not.toHaveBeenCalled();
    expect(batchSpy).toHaveBeenCalledTimes(1);
    const frame = batchSpy.mock.calls[0][0];
    expect(frame.type).toBe("batch");
    expect(frame.events.map((x: { event_id: string }) => x.event_id)).toEqual([
      "evt-1",
      "evt-2",
      "evt-3",
    ]);
  });

  it("on a single overflow event, flushes inline AND defers the warn until flushFrame (S-210)", async () => {
    const warnSpy = vi.spyOn(logger, "warn").mockImplementation(() => {});
    const batchSpy = vi.fn();
    const eventSpy = vi.fn();
    bus.on("batch", batchSpy);
    bus.on("event", eventSpy);

    for (let i = 0; i < 501; i++) {
      bus.emitCoalesced({
        ...eventMsg,
        data: { ...eventMsg.data, event_id: `evt-${i}` },
      });
    }

    // Inline 500-event flush still happens at the cap, but the warn is now
    // deferred to the flushFrame tick that emits the batch — not the per-event
    // overflow branch. So warnSpy must be untouched until rAF fires.
    expect(batchSpy).toHaveBeenCalledTimes(1);
    expect(batchSpy.mock.calls[0][0].events).toHaveLength(500);
    expect(warnSpy).not.toHaveBeenCalled();

    await vi.runAllTimersAsync();

    expect(warnSpy).toHaveBeenCalledTimes(1);
    // Total flushed across the rAF cycle: 500 inline (overflow) + 1 trailing rAF flush.
    expect(warnSpy).toHaveBeenCalledWith(
      "wsBus.rAF buffer overflow",
      { flushed: 501, overflow_count: 1 },
    );
    warnSpy.mockRestore();
  });

  it("accumulates multiple overflows in one tick into a single warn with overflow_count (S-210)", async () => {
    const warnSpy = vi.spyOn(logger, "warn").mockImplementation(() => {});
    const batchSpy = vi.fn();
    bus.on("batch", batchSpy);

    // 1500 events trigger overflow at 501 and again at 1001 → overflow_count=2.
    for (let i = 0; i < 1500; i++) {
      bus.emitCoalesced({
        ...eventMsg,
        data: { ...eventMsg.data, event_id: `evt-${i}` },
      });
    }
    expect(warnSpy).not.toHaveBeenCalled();
    expect(batchSpy).toHaveBeenCalledTimes(2);

    await vi.runAllTimersAsync();

    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(warnSpy.mock.calls[0][0]).toBe("wsBus.rAF buffer overflow");
    // Trace: 1500 events → 2 inline overflow flushes of 500 each + 500 trailing
    // rAF flush = 1500 total flushed across the cycle.
    expect(warnSpy.mock.calls[0][1]).toMatchObject({ flushed: 1500, overflow_count: 2 });
    warnSpy.mockRestore();
  });

  it("compresses 1k events into 2 batches under a single flush cycle (guards notify fan-out)", async () => {
    const warnSpy = vi.spyOn(logger, "warn").mockImplementation(() => {});
    const batchSpy = vi.fn();
    const eventSpy = vi.fn();
    bus.on("batch", batchSpy);
    bus.on("event", eventSpy);

    for (let i = 0; i < 1000; i++) {
      bus.emitCoalesced({
        ...eventMsg,
        data: { ...eventMsg.data, event_id: `evt-${i}` },
      });
    }

    // Trace: events 0..499 fill the buffer to capacity. The 501st push (event
    // index 500) trips the overflow branch, flushes 500 as a batch inline, then
    // lands event 500 on a fresh buffer. Events 501..999 pile on without another
    // overflow (buffer grows 1→500 in that second run). So after the synchronous
    // loop we observe exactly one inline batch (500 events) + one pending rAF.
    expect(batchSpy).toHaveBeenCalledTimes(1);
    expect(batchSpy.mock.calls[0][0].events).toHaveLength(500);
    // S-210: the warn is now deferred to flushFrame, so no warn fires inline.
    expect(warnSpy).not.toHaveBeenCalled();

    await vi.runAllTimersAsync();

    // The rAF tick flushes the second 500-event batch. No per-event notifies;
    // 1000 wire events → 2 downstream notify cycles = 500× reduction.
    expect(batchSpy).toHaveBeenCalledTimes(2);
    expect(batchSpy.mock.calls[1][0].events).toHaveLength(500);
    expect(eventSpy).not.toHaveBeenCalled();
    // S-210: a single summary warn fires at flush time, covering the one
    // overflow that occurred in the synchronous burst.
    expect(warnSpy).toHaveBeenCalledTimes(1);

    warnSpy.mockRestore();
  });
});
