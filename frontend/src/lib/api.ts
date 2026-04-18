const BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

export class ApiError extends Error {
  constructor(public status: number, public detail: string, public cause?: unknown) {
    super(`${status} ${detail}`);
    this.name = "ApiError";
  }
}

import { toBigintNs } from "./bigint-ns";

const BIGINT_KEYS = new Set(["timestamp_ns", "observed_ns", "bucket_start_ns"]);

/**
 * Walk a parsed JSON value and convert any key in BIGINT_KEYS whose value is
 * a digits-only string into a bigint. The backend serialises these fields as
 * JSON strings for JS bigint safety (S-194 for alert timestamps, S-199 for
 * every other *_ns field). Numeric values at those keys are left untouched
 * so this is a no-op on payloads that have not yet been migrated — required
 * for graceful two-sided deploys.
 */
function reviveBigintTimestamps(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(reviveBigintTimestamps);
  if (value && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(obj)) {
      if (BIGINT_KEYS.has(k) && typeof v === "string") {
        out[k] = toBigintNs(v);
      } else {
        out[k] = reviveBigintTimestamps(v);
      }
    }
    return out;
  }
  return value;
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
