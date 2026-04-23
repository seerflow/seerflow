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

beforeEach(() => bus._clearAllForTests());

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
    vi.stubGlobal("requestAnimationFrame", undefined);
    const spy = vi.fn();
    bus.on("event", spy);

    bus.emitCoalesced(eventMsg);

    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith(eventMsg);

    vi.unstubAllGlobals();
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

  it("flushes a partial batch and warns once when the frame buffer exceeds the cap", async () => {
    const warnSpy = vi.spyOn(logger, "warn").mockImplementation(() => {});
    const batchSpy = vi.fn();
    bus.on("batch", batchSpy);

    // Push 501 events synchronously before the first rAF fires.
    for (let i = 0; i < 501; i++) {
      bus.emitCoalesced({
        ...eventMsg,
        data: { ...eventMsg.data, event_id: `evt-${i}` },
      });
    }

    // Overflow triggers an immediate partial flush; the 501st event lands on a fresh buffer.
    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(warnSpy).toHaveBeenCalledWith(
      "wsBus.rAF buffer overflow",
      { dropped: 500 }
    );
    expect(batchSpy).toHaveBeenCalledTimes(1);
    expect(batchSpy.mock.calls[0][0].events).toHaveLength(500);

    await vi.runAllTimersAsync();

    // The 501st event flushes on the next rAF tick as a single event frame.
    expect(batchSpy).toHaveBeenCalledTimes(1); // no second batch
    warnSpy.mockRestore();
  });
});
