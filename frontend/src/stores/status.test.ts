import { describe, it, expect, beforeEach, afterEach } from "vitest";
import * as wsBus from "@/lib/wsBus";
import { useStatusStore } from "./status";

describe("useStatusStore", () => {
  beforeEach(() => {
    wsBus._clearAllForTests();
    // Reset store to initial defaults, then re-register the wsBus subscription
    // (clearAllForTests removes module-level subscriptions).
    useStatusStore.setState({
      pipelineOnline: false,
      uptimeLabel: "—",
      evPerSec: 0,
    });
    useStatusStore.getState()._resubscribe();
  });

  afterEach(() => {
    wsBus._clearAllForTests();
  });

  it("starts with pipelineOnline=false, evPerSec=0, uptimeLabel='—'", () => {
    const state = useStatusStore.getState();
    expect(state.pipelineOnline).toBe(false);
    expect(state.evPerSec).toBe(0);
    expect(state.uptimeLabel).toBe("—");
  });

  it("sets pipelineOnline=true on __status open event", () => {
    wsBus.emit({ type: "__status", status: "open" });
    expect(useStatusStore.getState().pipelineOnline).toBe(true);
  });

  it("sets pipelineOnline=false on __status closed event", () => {
    // First bring it online
    wsBus.emit({ type: "__status", status: "open" });
    expect(useStatusStore.getState().pipelineOnline).toBe(true);

    // Then disconnect
    wsBus.emit({ type: "__status", status: "closed" });
    expect(useStatusStore.getState().pipelineOnline).toBe(false);
  });

  it("exposes subscribe mechanism via zustand", () => {
    let lastState = useStatusStore.getState();
    const unsub = useStatusStore.subscribe((s) => {
      lastState = s;
    });
    wsBus.emit({ type: "__status", status: "open" });
    expect(lastState.pipelineOnline).toBe(true);
    unsub();
  });
});
