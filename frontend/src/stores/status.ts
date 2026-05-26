import { create } from "zustand";
import { on } from "@/lib/wsBus";

export interface StatusState {
  pipelineOnline: boolean;
  /** Human-readable uptime label, e.g. "4d 12h" or "—" when unknown */
  uptimeLabel: string;
  /** Events per second as last reported, 0 when unknown */
  evPerSec: number;
  /**
   * Re-register the wsBus subscription.
   * Called automatically at module init and after test bus resets.
   */
  _resubscribe: () => () => void;
}

function handleStatus(msg: { type: "__status"; status: string }): void {
  if (msg.status === "open") {
    useStatusStore.setState({ pipelineOnline: true });
  } else if (msg.status === "closed" || msg.status === "connecting") {
    useStatusStore.setState({ pipelineOnline: false });
  }
}

/**
 * Pipeline status store.
 *
 * Subscribes to `wsBus` `__status` events to track whether the backend
 * pipeline is connected. When the WebSocket is open, pipelineOnline=true.
 * When closed/connecting, pipelineOnline=false.
 *
 * uptimeLabel and evPerSec are held at their last known values when
 * disconnected (no reset on close), so the UI shows stale-but-stable numbers
 * rather than flashing "—" on brief reconnects.
 */
export const useStatusStore = create<StatusState>()(() => ({
  pipelineOnline: false,
  uptimeLabel: "—",
  evPerSec: 0,
  _resubscribe: () => on("__status", handleStatus),
}));

// Subscribe at module load so production code works without explicit init.
useStatusStore.getState()._resubscribe();
