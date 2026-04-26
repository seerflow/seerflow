import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  getSigmaRules,
  getSigmaRule,
  toggleSigmaRule,
  validateSigmaRule,
  uploadSigmaRule,
} from "./sigmaRulesApi";
import { api } from "./api";

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    api: { get: vi.fn(), post: vi.fn() },
  };
});

const mockedGet = api.get as unknown as ReturnType<typeof vi.fn>;
const mockedPost = api.post as unknown as ReturnType<typeof vi.fn>;

const sampleSummary = {
  rule_id: "r1",
  title: "T",
  description: "",
  severity: 3,
  logsource_key: ["", "linux", ""],
  attack_tactics: [],
  attack_techniques: [],
  enabled: true,
  source: "bundled",
  match_count_lifetime: 0,
  last_fired_ns: null,
  alert_count_24h: 0,
};

describe("getSigmaRules", () => {
  beforeEach(() => {
    mockedGet.mockReset();
  });

  it("calls /api/v1/sigma/rules with no query for empty params", async () => {
    mockedGet.mockResolvedValueOnce({ items: [], total: 0, page: 1, limit: 100 });
    await getSigmaRules();
    expect(mockedGet).toHaveBeenCalledWith(
      "/api/v1/sigma/rules",
      expect.objectContaining({ schema: expect.anything() }),
    );
  });

  it("builds query string from filters", async () => {
    mockedGet.mockResolvedValueOnce({ items: [], total: 0, page: 1, limit: 50 });
    await getSigmaRules({ page: 2, limit: 50, search: "ssh", enabled: true });
    const callPath = mockedGet.mock.calls[0][0] as string;
    expect(callPath).toContain("page=2");
    expect(callPath).toContain("limit=50");
    expect(callPath).toContain("search=ssh");
    expect(callPath).toContain("enabled=true");
  });

  it("skips empty/null/undefined filter values", async () => {
    mockedGet.mockResolvedValueOnce({ items: [], total: 0, page: 1, limit: 100 });
    await getSigmaRules({ search: "", category: undefined });
    const callPath = mockedGet.mock.calls[0][0] as string;
    expect(callPath).toBe("/api/v1/sigma/rules");
  });

  it("parses has_next in the list envelope", async () => {
    mockedGet.mockResolvedValueOnce({
      items: [],
      total: 0,
      page: 1,
      limit: 50,
      has_next: false,
    });
    const out = await getSigmaRules();
    expect(out.has_next).toBe(false);
  });
});

describe("getSigmaRule", () => {
  beforeEach(() => mockedGet.mockReset());

  it("encodes rule id and parses detail", async () => {
    mockedGet.mockResolvedValueOnce({ ...sampleSummary, yaml_source: "title: T" });
    const result = await getSigmaRule("r/1");
    expect(mockedGet).toHaveBeenCalledWith(
      "/api/v1/sigma/rules/r%2F1",
      expect.anything(),
    );
    expect(result.yaml_source).toBe("title: T");
  });
});

describe("validateSigmaRule + uploadSigmaRule", () => {
  beforeEach(() => mockedPost.mockReset());

  it("validateSigmaRule posts dry_run query", async () => {
    mockedPost.mockResolvedValueOnce({ valid: true, rule_id: "r1", title: "T" });
    await validateSigmaRule("title: T");
    const [path, body] = mockedPost.mock.calls[0];
    expect(path).toContain("?dry_run=true");
    expect(body).toEqual({ yaml: "title: T" });
  });

  it("uploadSigmaRule posts to /api/v1/sigma/rules", async () => {
    mockedPost.mockResolvedValueOnce({ ...sampleSummary, yaml_source: "title: T" });
    await uploadSigmaRule("title: T");
    expect(mockedPost.mock.calls[0][0]).toBe("/api/v1/sigma/rules");
  });
});

describe("toggleSigmaRule", () => {
  beforeEach(() => {
    vi.spyOn(globalThis, "fetch").mockReset();
  });

  it("issues PATCH with enabled body and parses response", async () => {
    const detail = { ...sampleSummary, yaml_source: "title: T", enabled: false };
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(detail), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    const result = await toggleSigmaRule("rid", false);
    expect(result.enabled).toBe(false);
    const [, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect((init as RequestInit).method).toBe("PATCH");
    expect((init as RequestInit).body).toContain('"enabled":false');
  });

  it("throws ApiError on non-OK response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "rule not found" }), {
        status: 404,
        headers: { "content-type": "application/json" },
      }),
    );
    await expect(toggleSigmaRule("rid", false)).rejects.toThrow(/rule not found/);
  });

  it("sanitises 5xx detail to GENERIC_5XX, preserves raw on debugDetail", async () => {
    const { ApiError } = await import("./api");
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: 'Traceback ... File "/srv/app.py", line 1' }), {
        status: 500,
        headers: { "content-type": "application/json" },
      }),
    );
    let caught: unknown;
    try { await toggleSigmaRule("rid", false); } catch (e) { caught = e; }
    expect(caught).toBeInstanceOf(ApiError);
    const err = caught as InstanceType<typeof ApiError>;
    expect(err.status).toBe(500);
    expect(err.detail).toBe(ApiError.GENERIC_5XX);
    expect(err.debugDetail).toContain("Traceback");
  });
});
