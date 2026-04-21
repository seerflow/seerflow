import type { WsMessage } from "./types";
import { logger } from "./logger";

type WsType = WsMessage["type"];
type Handler<T extends WsType> = (msg: Extract<WsMessage, { type: T }>) => void;
// Storage erasure: handlers stored under key `T` are only invoked via `emit`
// on a `msg` where `msg.type === T`, so the `Handler<T>` → `AnyHandler` cast
// below is safe. The public `on<T>` signature still narrows the handler
// parameter at the call site.
type AnyHandler = (msg: WsMessage) => void;

const handlers = new Map<WsType, Set<AnyHandler>>();

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
    catch (e) { logger.warn("wsBus handler threw", { type: msg.type, error: e }); }
  }
}

// Must not REPLACE the stored Sets — unsubscribe closures returned by `on`
// capture the live Set reference. `clear()` in place keeps those closures
// valid; swapping to a fresh Set would silently detach them.
export function clearAll(): void {
  for (const set of handlers.values()) {
    set.clear();
  }
}
