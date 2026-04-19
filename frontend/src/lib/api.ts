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
const REVIVE_MAX_DEPTH = 32;

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
    const body = typeof parsed === "object" && parsed !== null ? reviveBigintTimestamps(parsed) : parsed;
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
