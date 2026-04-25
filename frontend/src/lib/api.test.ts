import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { api, ApiError, sanitizeDetail, __walker } from "./api";
import { logger } from "./logger";
import { AlertSchema } from "./schemas";
import * as metrics from "./validationMetrics";

const fetchMock = vi.fn();

describe("api", () => {
  beforeEach(() => { vi.stubGlobal("fetch", fetchMock); fetchMock.mockReset(); });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("GET returns parsed JSON on 200", async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({items: []}), {status: 200, headers: {"content-type":"application/json"}}));
    const result = await api.get<{items: unknown[]}>("/api/v1/alerts?limit=50");
    expect(result.items).toEqual([]);
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/alerts?limit=50", expect.objectContaining({method: "GET"}));
  });

  it("POST sends JSON body", async () => {
    fetchMock.mockResolvedValueOnce(new Response("{}", {status: 200, headers: {"content-type":"application/json"}}));
    await api.post("/api/v1/alerts/x/feedback", {feedback: "tp"});
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body as string)).toEqual({feedback: "tp"});
  });

  it("throws ApiError on 4xx", async () => {
    fetchMock.mockResolvedValueOnce(new Response("{\"detail\":\"nope\"}", {status: 422, headers: {"content-type":"application/json"}}));
    await expect(api.get("/api/v1/alerts/bad")).rejects.toBeInstanceOf(ApiError);
  });

  it("throws ApiError on network failure", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("network"));
    await expect(api.get("/api/v1/alerts")).rejects.toBeInstanceOf(ApiError);
  });

  it("throws ApiError with raw text body when non-JSON error response (S-204 AC-2)", async () => {
    fetchMock.mockResolvedValueOnce(new Response("boom", {status: 500, headers: {"content-type": "text/plain"}}));
    await expect(api.get("/api/v1/thing")).rejects.toMatchObject({
      name: "ApiError",
      status: 500,
      detail: "boom",
    });
  });

  it("re-throws existing ApiError unchanged rather than wrapping (S-204 AC-3)", async () => {
    fetchMock.mockResolvedValueOnce(new Response("{\"detail\":\"nope\"}", {status: 422, headers: {"content-type": "application/json"}}));
    const err = await api.get("/api/v1/bad").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(422);
    expect((err as ApiError).detail).toBe("nope");
  });
});

describe("api boundary parsing", () => {
  beforeEach(() => { vi.stubGlobal("fetch", fetchMock); fetchMock.mockReset(); __walker.reset(); });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("parses timestamp_ns string into bigint without precision loss (S-194 AC-1)", async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({
      items: [{
        alert_id: "a1",
        timestamp_ns: "1700000000000000123",
        alert_type: "ml", rule_name: "r", severity: 3, risk_score: 0,
        entity_uuid: "u", entity_type: "ip", entity_value: "x",
        message: "m", mitre_tactics: [], mitre_techniques: [], dedup_count: 1,
      }],
    }), { status: 200, headers: {"content-type":"application/json"} }));
    const res = await api.get<{ items: { timestamp_ns: bigint }[] }>("/api/v1/alerts?limit=1");
    expect(res.items[0].timestamp_ns).toBe(1700000000000000123n);
  });

  it("leaves numeric timestamp_ns unchanged for non-alert responses (S-194)", async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({
      events: [{ event_id: "e1", timestamp_ns: 1234567890 }],
    }), { status: 200, headers: {"content-type":"application/json"} }));
    const res = await api.get<{ events: { timestamp_ns: number }[] }>("/api/v1/some-other");
    expect(res.events[0].timestamp_ns).toBe(1234567890);
    expect(typeof res.events[0].timestamp_ns).toBe("number");
    // S-203 AC-3: numeric bigint-keyed values must short-circuit before the walker runs.
    expect(__walker.calls).toBe(0);
  });

  it("leaves numeric observed_ns unchanged when wire still emits int (S-199 deploy window)", async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({
      events: [{ event_id: "e1", observed_ns: 1234567890 }],
    }), { status: 200, headers: {"content-type":"application/json"} }));
    const res = await api.get<{ events: { observed_ns: number }[] }>("/api/v1/events");
    expect(res.events[0].observed_ns).toBe(1234567890);
    expect(typeof res.events[0].observed_ns).toBe("number");
  });

  it("leaves numeric bucket_start_ns unchanged when wire still emits int (S-199 deploy window)", async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({
      items: [{ bucket_start_ns: 1234567890, max_score: 0.1 }],
    }), { status: 200, headers: {"content-type":"application/json"} }));
    const res = await api.get<{ items: { bucket_start_ns: number }[] }>("/api/v1/anomaly/timeline");
    expect(res.items[0].bucket_start_ns).toBe(1234567890);
    expect(typeof res.items[0].bucket_start_ns).toBe("number");
  });

  it("leaves over-long timestamp_ns string unconverted (S-199 DoS guard)", async () => {
    // A 26-digit string exceeds MAX_NS_STRING_LEN (25). The walker must return
    // the raw string rather than spending O(n^2) time on a giant BigInt.
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({
      items: [{ alert_id: "a1", timestamp_ns: "1".repeat(26) }],
    }), { status: 200, headers: {"content-type":"application/json"} }));
    const res = await api.get<{ items: { timestamp_ns: unknown }[] }>("/api/v1/alerts?limit=1");
    expect(res.items[0].timestamp_ns).toBe("1".repeat(26));
    expect(typeof res.items[0].timestamp_ns).toBe("string");
  });

  it("falls back to string timestamp_ns when BigInt() throws (defensive)", async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({
      items: [{ alert_id: "a1", timestamp_ns: "not-a-number" }],
    }), { status: 200, headers: {"content-type":"application/json"} }));
    const res = await api.get<{ items: { timestamp_ns: unknown }[] }>("/api/v1/alerts?limit=1");
    expect(res.items[0].timestamp_ns).toBe("not-a-number");
  });

  it("parses observed_ns string into bigint without precision loss (S-199 AC-5)", async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({
      items: [{ event_id: "e1", observed_ns: "1700000000000000123" }],
    }), { status: 200, headers: {"content-type":"application/json"} }));
    const res = await api.get<{ items: { observed_ns: bigint }[] }>("/api/v1/events?limit=1");
    expect(res.items[0].observed_ns).toBe(1700000000000000123n);
  });

  it("parses bucket_start_ns string into bigint without precision loss (S-199 AC-5)", async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({
      items: [{ bucket_start_ns: "1700000000000000123", max_score: 0.9 }],
    }), { status: 200, headers: {"content-type":"application/json"} }));
    const res = await api.get<{ items: { bucket_start_ns: bigint }[] }>("/api/v1/anomaly/timeline");
    expect(res.items[0].bucket_start_ns).toBe(1700000000000000123n);
  });

  it("caps reviveBigintTimestamps recursion at depth 32 and warns once (S-203 AC-2)", async () => {
    let payload: Record<string, unknown> = { timestamp_ns: "1700000000000000123" };
    for (let i = 0; i < 64; i++) payload = { nested: payload };
    // Wrap so the outermost key has its own timestamp_ns at depth 0 — proves the walker still works above the cap.
    payload = { ...payload, timestamp_ns: "1700000000000000999" };
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify(payload), { status: 200, headers: { "content-type": "application/json" } }),
    );
    const warn = vi.spyOn(logger, "warn").mockImplementation(() => {});
    const res = await api.get<Record<string, unknown>>("/api/v1/deep");
    // Depth-0 conversion must still happen — proves the walker is not silently broken.
    expect((res as Record<string, unknown>).timestamp_ns).toBe(1700000000000000999n);
    // Past the cap, the deepest timestamp_ns is left as the wire string (graceful degrade).
    let cursor: unknown = res;
    let foundString = false;
    while (cursor && typeof cursor === "object") {
      const c = cursor as Record<string, unknown>;
      if (typeof c.timestamp_ns === "string") { foundString = true; break; }
      cursor = c.nested;
    }
    expect(foundString).toBe(true);
    expect(warn).toHaveBeenCalledTimes(1);
    warn.mockRestore();
  });

  it("walker does not enter the object branch when no bigint markers exist (S-203 AC-3)", async () => {
    const payload = { ok: true, version: "1.2.3", nested: { extra: ["a", { deeper: 42 }] } };
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify(payload), { headers: { "content-type": "application/json" } }),
    );
    await api.get("/api/v1/health");
    expect(__walker.calls).toBe(0);
  });

  it("strips __proto__ keys from revived responses to prevent prototype pollution", async () => {
    // JSON.parse produces a literal __proto__ own-property — regular object
    // literals don't, so we must construct the poisoned body via JSON.parse.
    const poisoned = JSON.parse('{"__proto__":{"timestamp_ns":"123"},"ok":true,"inner":{"timestamp_ns":"456"}}');
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify(poisoned), { status: 200, headers: { "content-type": "application/json" } }),
    );
    const res = await api.get<{ ok: boolean }>("/api/v1/x");
    expect(res.ok).toBe(true);
    // Prototype must remain the vanilla Object.prototype — no pollution.
    expect(Object.getPrototypeOf(res)).toBe(Object.prototype);
    // Access via prototype lookup — should not return the poisoned value.
    expect((res as unknown as { timestamp_ns?: bigint }).timestamp_ns).toBeUndefined();
    // Defence-in-depth: also check a fresh object's prototype is uncontaminated.
    expect(({} as unknown as { timestamp_ns?: bigint }).timestamp_ns).toBeUndefined();
  });
});

describe("api schema opt-in", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockReset();
    metrics._resetForTests();
  });
  afterEach(() => { vi.unstubAllGlobals(); });

  const validAlertWire = {
    alert_id: "a1",
    timestamp_ns: "1700000000000000123",
    alert_type: "sigma",
    rule_name: "r",
    severity: 3,
    risk_score: 0.5,
    entity_uuid: null,
    entity_type: null,
    entity_value: null,
    message: "m",
    mitre_tactics: [],
    mitre_techniques: [],
    dedup_count: 1,
  };

  it("throws ApiError on scalar schema fail", async () => {
    const bad = { alert_id: 999 };
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify(bad), { status: 200, headers: { "content-type": "application/json" } }),
    );
    await expect(api.get("/api/v1/alerts/x", { schema: AlertSchema })).rejects.toThrow(/response-schema-fail/);
  });

  it("validates list items under itemsKey and filters invalid ones", async () => {
    const items = [validAlertWire, { ...validAlertWire, severity: 999 }];
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ items, total: 2, page: 0, limit: 50, has_next: false }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    const res = await api.get<{ items: unknown[] }>("/api/v1/alerts?limit=50", {
      schema: AlertSchema,
      itemsKey: "items",
    });
    expect(res.items.length).toBe(1);
    expect(metrics.getCounters()["rest:/api/v1/alerts"]).toBe(1);
  });

  it("passes through unchanged when no schema is provided", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ x: 1 }), { status: 200, headers: { "content-type": "application/json" } }),
    );
    const res = await api.get<{ x: number }>("/api/v1/x");
    expect(res).toEqual({ x: 1 });
  });

  it("throws ApiError when itemsKey is missing or not an array", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ notItems: [] }), { status: 200, headers: { "content-type": "application/json" } }),
    );
    await expect(
      api.get("/api/v1/alerts?limit=50", { schema: AlertSchema, itemsKey: "items" }),
    ).rejects.toThrow(/response-schema-fail/);
  });
});

describe("sanitizeDetail", () => {
  it("5xx JSON detail → generic display, raw debug", () => {
    const out = sanitizeDetail(500, 'Traceback (most recent call last)\n  File "/srv/app.py", line 42 ...');
    expect(out.display).toBe(ApiError.GENERIC_5XX);
    expect(out.debug).toContain("Traceback");
  });
  it("5xx plain-text body → generic display, raw debug", () => {
    const out = sanitizeDetail(503, "upstream timeout");
    expect(out.display).toBe(ApiError.GENERIC_5XX);
    expect(out.debug).toBe("upstream timeout");
  });
  it("4xx ≤200 chars → unchanged display, same as debug", () => {
    const out = sanitizeDetail(422, "tactic must be one of: collection, persistence, …");
    expect(out.display).toBe("tactic must be one of: collection, persistence, …");
    expect(out.debug).toBe(out.display);
  });
  it("4xx >200 chars → truncated display, full debug", () => {
    const long = "x".repeat(500);
    const out = sanitizeDetail(400, long);
    expect(out.display).toHaveLength(200);                 // 199 chars + "…"
    expect(out.display.endsWith("…")).toBe(true);
    expect(out.display.startsWith("xxx")).toBe(true);
    expect(out.debug).toBe(long);
  });
  it("status 0 (network / schema-fail) → pass-through, no sanitisation", () => {
    const out = sanitizeDetail(0, "response-schema-fail: items[3] invalid");
    expect(out.display).toBe("response-schema-fail: items[3] invalid");
    expect(out.debug).toBe(out.display);
  });
  it("3xx redirects (defensive) → pass-through", () => {
    const out = sanitizeDetail(301, "moved");
    expect(out.display).toBe("moved");
  });
});
