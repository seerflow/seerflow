import { create } from "zustand";
import { on } from "@/lib/wsBus";

export interface StatusState {
  pipelineOnline: boolean;
  /** Human-readable uptime label, e.g. "4d 12h" or "—" when unknown */
  uptimeLabel: string;
  /** Events per second as last reported, 0 when unknown */
  evPerSec: number;
  /** Distinct active entities as last reported, 0 when unknown (S-328) */
  activeEntities: number;
  /** Mean ingest latency in ms as last reported, 0 when unknown (S-328) */
  meanLatencyMs: number;
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
 *
 * activeEntities and meanLatencyMs (S-328) default to 0 until a live pipeline
 * metrics frame populates them; consumers fall back to demo values via the
 * `liveStats` selectors meanwhile.
 */
export const useStatusStore = create<StatusState>()(() => ({
  pipelineOnline: false,
  uptimeLabel: "—",
  evPerSec: 0,
  activeEntities: 0,
  meanLatencyMs: 0,
  _resubscribe: () => on("__status", handleStatus),
}));

// Subscribe at module load so production code works without explicit init.
useStatusStore.getState()._resubscribe();
