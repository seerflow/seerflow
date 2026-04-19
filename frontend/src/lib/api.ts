const BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

export class ApiError extends Error {
  constructor(public status: number, public detail: string, public cause?: unknown) {
    super(`${status} ${detail}`);
    this.name = "ApiError";
  }
}

import { toBigintNs } from "./bigint-ns";
import { logger } from "./logger";

const BIGINT_KEYS = new Set(["timestamp_ns", "observed_ns", "bucket_start_ns"]);
// 32 ≈ 6× headroom over the deepest legitimate Seerflow payload (≤5 levels:
// alert object inside an items array inside the response root). Caps the
// walker before V8's ~3,900-frame stack limit triggers RangeError on a
// crafted nested payload (S-203 AC-2).
const REVIVE_MAX_DEPTH = 32;

function hasBigintMarker(value: unknown, depth: number = 0): boolean {
  if (depth >= REVIVE_MAX_DEPTH) return false;
  if (Array.isArray(value)) {
    for (const v of value) if (hasBigintMarker(v, depth + 1)) return true;
    return false;
  }
  if (value && typeof value === "object") {
    for (const [k, v] of Object.entries(value)) {
      if (BIGINT_KEYS.has(k) && typeof v === "string") return true;
      if (hasBigintMarker(v, depth + 1)) return true;
    }
  }
  return false;
}

// Test-only counter — Task 3 of S-203 uses it to assert the walker did not
// allocate when no bigint marker exists in the payload. Production code
// never reads it.
export const __walker = { calls: 0, reset(): void { this.calls = 0; } };

/**
 * Walk a parsed JSON value and convert any key in BIGINT_KEYS whose value is
 * a digits-only string into a bigint. The backend serialises these fields as
 * JSON strings for JS bigint safety (S-194 for alert timestamps, S-199 for
 * every other *_ns field). Numeric values at those keys are left untouched
 * so this is a no-op on payloads that have not yet been migrated — required
 * for graceful two-sided deploys.
 *
 * Recursion is capped at depth 32 to prevent RangeError on deeply nested
 * payloads (S-203). When the cap is hit, nested values are left unchanged
 * (graceful degrade).
 */
function reviveBigintTimestamps(value: unknown): unknown {
  let warnedDepth = false;
  function walk(v: unknown, depth: number): unknown {
    if (depth >= REVIVE_MAX_DEPTH) {
      if (!warnedDepth) { logger.warn("revive depth cap"); warnedDepth = true; }
      return v;
    }
    if (Array.isArray(v)) return v.map(x => walk(x, depth + 1));
    if (v && typeof v === "object") {
      __walker.calls++;
      const obj = v as Record<string, unknown>;
      const out: Record<string, unknown> = {};
      for (const [k, vv] of Object.entries(obj)) {
        if (BIGINT_KEYS.has(k) && typeof vv === "string") {
          out[k] = toBigintNs(vv);
        } else {
          out[k] = walk(vv, depth + 1);
        }
      }
      return out;
    }
    return v;
  }
  return walk(value, 0);
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  try {
    const res = await fetch(`${BASE}${path}`, init);
    const text = await res.text();
    const parsed = text && res.headers.get("content-type")?.includes("json") ? JSON.parse(text) : text;
    if (!res.ok) throw new ApiError(res.status, (parsed && typeof parsed === "object" && "detail" in parsed) ? String(parsed.detail) : text);
    const body = (typeof parsed === "object" && parsed !== null && hasBigintMarker(parsed))
      ? reviveBigintTimestamps(parsed)
      : parsed;
    return body as T;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    throw new ApiError(0, e instanceof Error ? e.message : String(e), e);
  }
}

interface GetOpts { signal?: AbortSignal }

export const api = {
  get:  <T,>(path: string, opts?: GetOpts) => request<T>(path, {method: "GET", headers: {"Accept": "application/json"}, signal: opts?.signal}),
  post: <T,>(path: string, body: unknown) =>
    request<T>(path, {method: "POST", headers: {"Content-Type": "application/json", "Accept": "application/json"}, body: JSON.stringify(body)}),
};
