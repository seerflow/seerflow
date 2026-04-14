import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { api, ApiError } from "./api";

describe("api", () => {
  const fetchMock = vi.fn();
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
