import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  getSigmaRules,
  getSigmaRule,
  getSigmaRuleTimeline,
  toggleSigmaRule,
  validateSigmaRule,
  uploadSigmaRule,
} from "./sigmaRulesApi";
import { api } from "./api";

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  };
});

const mockedGet = api.get as unknown as ReturnType<typeof vi.fn>;
const mockedPost = api.post as unknown as ReturnType<typeof vi.fn>;
const mockedPatch = api.patch as unknown as ReturnType<typeof vi.fn>;

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

  it("round-trips has_next: true", async () => {
    mockedGet.mockResolvedValueOnce({
      items: [],
      total: 100,
      page: 1,
      limit: 50,
      has_next: true,
    });
    const out = await getSigmaRules();
    expect(out.has_next).toBe(true);
  });

  it("buildQuery repeats severity_in for each value", async () => {
    mockedGet.mockResolvedValueOnce({ items: [], total: 0, page: 1, limit: 100 });
    await getSigmaRules({ severity_in: [3, 4] });
    const callPath = mockedGet.mock.calls[0][0] as string;
    expect(callPath.startsWith("/api/v1/sigma/rules?")).toBe(true);
    const qs = callPath.slice(callPath.indexOf("?") + 1);
    const params = new URLSearchParams(qs);
    expect(params.getAll("severity_in")).toEqual(["3", "4"]);
  });

  it("buildQuery omits severity_in when the array is empty", async () => {
    mockedGet.mockResolvedValueOnce({ items: [], total: 0, page: 1, limit: 100 });
    await getSigmaRules({ severity_in: [] });
    const callPath = mockedGet.mock.calls[0][0] as string;
    expect(callPath).toBe("/api/v1/sigma/rules");
  });
});

describe("getSigmaRuleTimeline", () => {
  beforeEach(() => mockedGet.mockReset());

  it("calls /timeline with bucket=hour&window=24h and encodes the rule id", async () => {
    mockedGet.mockResolvedValueOnce({ buckets: [] });
    await getSigmaRuleTimeline("r/1");
    expect(mockedGet).toHaveBeenCalledWith(
      "/api/v1/sigma/rules/r%2F1/timeline?bucket=hour&window=24h",
      expect.objectContaining({ schema: expect.anything() }),
    );
  });

  it("returns the parsed response", async () => {
    mockedGet.mockResolvedValueOnce({
      buckets: [{ bucket_start_ns: 1n, count: 2 }],
    });
    const out = await getSigmaRuleTimeline("rid");
    expect(out.buckets).toHaveLength(1);
    expect(out.buckets[0].count).toBe(2);
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
  beforeEach(() => mockedPatch.mockReset());

  it("issues PATCH with enabled body and returns parsed detail", async () => {
    const detail = { ...sampleSummary, yaml_source: "title: T", enabled: false };
    mockedPatch.mockResolvedValueOnce(detail);
    const result = await toggleSigmaRule("rid", false);
    expect(result.enabled).toBe(false);
    const [path, body, opts] = mockedPatch.mock.calls[0];
    expect(path).toBe("/api/v1/sigma/rules/rid");
    expect(body).toEqual({ enabled: false });
    expect(opts).toEqual(expect.objectContaining({ schema: expect.anything() }));
  });

  it("encodes rule id segments", async () => {
    mockedPatch.mockResolvedValueOnce({ ...sampleSummary, yaml_source: "title: T" });
    await toggleSigmaRule("r/1", true);
    expect(mockedPatch.mock.calls[0][0]).toBe("/api/v1/sigma/rules/r%2F1");
  });

  it("propagates ApiError from api.patch (e.g. 404)", async () => {
    const { ApiError } = await import("./api");
    mockedPatch.mockRejectedValueOnce(new ApiError(404, "rule not found"));
    await expect(toggleSigmaRule("rid", false)).rejects.toThrow(/rule not found/);
  });
});
