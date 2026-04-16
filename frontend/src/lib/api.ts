const BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

export class ApiError extends Error {
  constructor(public status: number, public detail: string, public cause?: unknown) {
    super(`${status} ${detail}`);
    this.name = "ApiError";
  }
}

/**
 * Walk a parsed JSON value and convert any `timestamp_ns` key whose value is a string
 * into a bigint. The backend serialises `Alert.timestamp_ns` as a JSON string for JS
 * bigint safety (S-194). Numeric `timestamp_ns` values (used by other endpoints such
 * as the entity timeline) are left untouched.
 */
function reviveAlertTimestamps(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(reviveAlertTimestamps);
  if (value && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(obj)) {
      if (k === "timestamp_ns" && typeof v === "string") {
        try { out[k] = BigInt(v); }
        catch { out[k] = v; }  // leave as string; caller decides
      } else {
        out[k] = reviveAlertTimestamps(v);
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
    const body = typeof parsed === "object" && parsed !== null ? reviveAlertTimestamps(parsed) : parsed;
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
