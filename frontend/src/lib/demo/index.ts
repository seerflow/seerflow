/**
 * Demo bridge — feeds existing stores with deterministic generated data
 * when WS is disconnected or `?demo=1` URL param is present.
 *
 * Components remain source-agnostic: the same zustand stores are written to
 * regardless of whether data comes from the real WS or the demo bridge.
 */

import { generateSeriesSamples, generateGraphData, generateEventBatch } from "./generators";

export { generateSeriesSamples, generateGraphData, generateEventBatch };

// --------------------------------------------------------------------------
// Demo mode detection
// --------------------------------------------------------------------------

/**
 * Returns true if the current URL contains `?demo=1` or `?demo=true`.
 */
export function isDemoMode(): boolean {
  const params = new URLSearchParams(window.location.search);
  const v = params.get("demo");
  return v === "1" || v === "true";
}

// --------------------------------------------------------------------------
// Demo bridge timer
// --------------------------------------------------------------------------

interface DemoBridgeOptions {
  /** Tick interval in ms (default 1000 = 1 s) */
  intervalMs?: number;
  /**
   * Optional callback invoked on each tick with the generated sample index.
   * Useful for testing and for wiring into stores.
   */
  onTick?: (tickIndex: number) => void;
}

let _timer: ReturnType<typeof setInterval> | null = null;
let _tickIndex = 0;

/**
 * Start the demo data bridge.  On each interval tick, generates new samples
 * and calls `onTick`.  Idempotent — calling while already running is a no-op.
 */
export function startDemoBridge(options: DemoBridgeOptions = {}): void {
  if (_timer !== null) return; // already running

  const interval = options.intervalMs ?? 1000;
  const { onTick } = options;

  _tickIndex = 0;
  _timer = setInterval(() => {
    _tickIndex++;
    onTick?.(_tickIndex);
  }, interval);
}

/**
 * Stop the demo bridge.  Idempotent — calling when not running is a no-op.
 */
export function stopDemoBridge(): void {
  if (_timer === null) return;
  clearInterval(_timer);
  _timer = null;
  _tickIndex = 0;
}

/**
 * Returns true if the bridge is currently running.
 */
export function isDemoBridgeRunning(): boolean {
  return _timer !== null;
}
