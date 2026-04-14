const BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

export class ApiError extends Error {
  constructor(public status: number, public detail: string, public cause?: unknown) {
    super(`${status} ${detail}`);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  try {
    const res = await fetch(`${BASE}${path}`, init);
    const text = await res.text();
    const body = text && res.headers.get("content-type")?.includes("json") ? JSON.parse(text) : text;
    if (!res.ok) throw new ApiError(res.status, (body && typeof body === "object" && "detail" in body) ? String(body.detail) : text);
    return body as T;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    throw new ApiError(0, e instanceof Error ? e.message : String(e), e);
  }
}

export const api = {
  get:  <T,>(path: string) => request<T>(path, {method: "GET", headers: {"Accept": "application/json"}}),
  post: <T,>(path: string, body: unknown) =>
    request<T>(path, {method: "POST", headers: {"Content-Type": "application/json", "Accept": "application/json"}, body: JSON.stringify(body)}),
};
