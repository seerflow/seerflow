import type { LiveEvent, WsMessage } from "./types";
import { logger } from "./logger";

type WsType = WsMessage["type"];
type Handler<T extends WsType> = (msg: Extract<WsMessage, { type: T }>) => void;
// Storage erasure: handlers stored under key `T` are only invoked via `emit`
// on a `msg` where `msg.type === T`, so the `Handler<T>` → `AnyHandler` cast
// below is safe. The public `on<T>` signature still narrows the handler
// parameter at the call site.
type AnyHandler = (msg: WsMessage) => void;

const handlers = new Map<WsType, Set<AnyHandler>>();

let rafFrameBuffer: LiveEvent[] = [];
let rafScheduled = false;
let overflowCount = 0;
let flushedInCycle = 0;
const RAF_BUFFER_MAX = 500;

function flushFrame(fromRaf = false): void {
  if (fromRaf) {
    rafScheduled = false;
  }
  const events = rafFrameBuffer;
  rafFrameBuffer = [];
  // Always tally what we just flushed so the rAF-cycle summary reports the
  // true total (inline overflow flushes + the trailing rAF flush). Without
  // this, `flushed` in the summary warn would only report the residual buffer
  // at rAF time and miss the 500-event inline batches entirely.
  flushedInCycle += events.length;
  // Only the rAF-scheduled flush consumes the cycle accumulators. Inline
  // overflow flushes leave both intact so they accumulate across the tick and
  // are reported once when the rAF callback finally runs.
  const overflows = fromRaf ? overflowCount : 0;
  const flushed = fromRaf ? flushedInCycle : 0;
  if (fromRaf) {
    overflowCount = 0;
    flushedInCycle = 0;
  }
  if (events.length === 0 && overflows === 0) return;
  if (overflows > 0) {
    // S-210: collapse N per-overflow warns into a single summary at flush time.
    // `flushed` is the total event count across the entire rAF cycle (inline
    // overflow batches + trailing rAF flush), not the residual buffer length.
    logger.warn("wsBus.rAF buffer overflow", {
      flushed,
      overflow_count: overflows,
    });
  }
  if (events.length === 0) return;
  if (events.length === 1) {
    emit({ type: "event", data: events[0] });
  } else {
    emit({ type: "batch", events });
  }
}

export function on<T extends WsType>(type: T, handler: Handler<T>): () => void {
  let set = handlers.get(type);
  if (!set) {
    set = new Set<AnyHandler>();
    handlers.set(type, set);
  }
  const erased = handler as AnyHandler;
  set.add(erased);
  return () => { set.delete(erased); };
}

export function emit(msg: WsMessage): void {
  const set = handlers.get(msg.type);
  if (!set) return;
  for (const h of set) {
    try { h(msg); }
    catch (e) {
      // Log a stringified message only — handler errors may embed message-data
      // fields (event_id, entity_value, etc.) in their `message` or nested
      // properties, which we do not want serialized verbatim into console logs.
      logger.warn("wsBus handler threw", {
        type: msg.type,
        error: e instanceof Error ? e.message : String(e),
      });
    }
  }
}

// Must not REPLACE the stored Sets — unsubscribe closures returned by `on`
// capture the live Set reference. `_clearAllForTests()` clears in place so
// those closures stay valid; swapping to a fresh Set would silently detach them.
export function _clearAllForTests(): void {
  for (const set of handlers.values()) {
    set.clear();
  }
}

/**
 * @deprecated S-208: use `_clearAllForTests` instead. This alias is kept for
 * one release cycle for any out-of-repo importer. Prod code must never clear
 * the bus; only test setup calls this.
 */
export const clearAll = _clearAllForTests;

export function emitCoalesced(msg: WsMessage): void {
  if (msg.type !== "event") {
    emit(msg);
    return;
  }
  if (typeof requestAnimationFrame !== "function") {
    emit(msg);
    return;
  }
  if (rafFrameBuffer.length >= RAF_BUFFER_MAX) {
    overflowCount += 1;
    flushFrame();
  }
  rafFrameBuffer.push(msg.data);
  if (!rafScheduled) {
    rafScheduled = true;
    requestAnimationFrame(() => flushFrame(true));
  }
}

export function _resetFrameBufferForTests(): void {
  rafFrameBuffer = [];
  rafScheduled = false;
  overflowCount = 0;
  flushedInCycle = 0;
}
