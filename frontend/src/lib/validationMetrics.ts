import { logger } from "./logger";

const THROTTLE_MS = 60_000;

const counters = new Map<string, number>();
const lastWarnAt = new Map<string, number>();

export function incrementDropped(kind: string): void {
  counters.set(kind, (counters.get(kind) ?? 0) + 1);
}

export function getCounters(): Readonly<Record<string, number>> {
  return Object.fromEntries(counters.entries());
}

export function warnThrottled(kind: string, issues: unknown): void {
  const now = Date.now();
  const prev = lastWarnAt.get(kind) ?? 0;
  if (now - prev < THROTTLE_MS) return;
  lastWarnAt.set(kind, now);
  logger.warn("payload-validation-drop", { kind, issues });
}

export function _resetForTests(): void {
  counters.clear();
  lastWarnAt.clear();
}
