import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { api, ApiError } from "./api";

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
});

describe("api boundary parsing", () => {
  beforeEach(() => { vi.stubGlobal("fetch", fetchMock); fetchMock.mockReset(); });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("parses timestamp_ns string into bigint without precision loss (S-194 AC-1)", async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({
      items: [{
        alert_id: "a1",
        timestamp_ns: "1700000000000000123",
        alert_type: "ml", rule_name: "r", severity: 10, risk_score: 0,
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
});
