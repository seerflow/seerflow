import { describe, it, expect, beforeEach, vi } from "vitest";
import * as bus from "./wsBus";
import type { WsMessage } from "./types";

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

beforeEach(() => bus.clearAll());

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
