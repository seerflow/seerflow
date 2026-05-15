import { describe, it, expect, vi, beforeEach } from "vitest";
import { useSigmaRulesStore } from "./sigmaRules";
import * as sigmaApi from "@/lib/sigmaRulesApi";

vi.mock("@/lib/sigmaRulesApi", () => ({
  getSigmaRules: vi.fn(),
  toggleSigmaRule: vi.fn(),
}));

const mockedGet = sigmaApi.getSigmaRules as unknown as ReturnType<typeof vi.fn>;
const mockedToggle = sigmaApi.toggleSigmaRule as unknown as ReturnType<typeof vi.fn>;

const sampleRule = {
  rule_id: "r1",
  title: "Sample",
  description: "",
  severity: 3,
  logsource_key: ["", "linux", ""] as [string, string, string],
  attack_tactics: [],
  attack_techniques: [],
  enabled: true,
  source: "bundled" as const,
  match_count_lifetime: 0,
  last_fired_ns: null,
  alert_count_24h: 0,
};

describe("useSigmaRulesStore", () => {
  beforeEach(() => {
    mockedGet.mockReset();
    mockedToggle.mockReset();
    useSigmaRulesStore.getState().reset();
  });

  it("starts in idle state", () => {
    const s = useSigmaRulesStore.getState();
    expect(s.status).toBe("idle");
    expect(s.rules).toEqual([]);
    expect(s.total).toBe(0);
  });

  it("load populates rules and sets status=ready", async () => {
    mockedGet.mockResolvedValueOnce({
      items: [sampleRule],
      total: 1,
      page: 1,
      limit: 100,
    });
    await useSigmaRulesStore.getState().load();
    const s = useSigmaRulesStore.getState();
    expect(s.rules).toHaveLength(1);
    expect(s.status).toBe("ready");
    expect(s.total).toBe(1);
  });

  it("load sets status=error on fetch failure", async () => {
    mockedGet.mockRejectedValueOnce(new Error("network"));
    await useSigmaRulesStore.getState().load();
    expect(useSigmaRulesStore.getState().status).toBe("error");
  });

  it("load forwards the AbortSignal to getSigmaRules (S-230)", async () => {
    mockedGet.mockResolvedValueOnce({
      items: [sampleRule],
      total: 1,
      page: 1,
      limit: 100,
    });
    const controller = new AbortController();
    await useSigmaRulesStore.getState().load(controller.signal);
    expect(mockedGet).toHaveBeenCalledTimes(1);
    expect(mockedGet.mock.calls[0][1]).toBe(controller.signal);
  });

  it("load does not set status=error when rejected with AbortError (S-230)", async () => {
    mockedGet.mockRejectedValueOnce(
      new DOMException("aborted", "AbortError"),
    );
    const controller = new AbortController();
    await useSigmaRulesStore.getState().load(controller.signal);
    expect(useSigmaRulesStore.getState().status).not.toBe("error");
    expect(useSigmaRulesStore.getState().status).toBe("loading");
  });

  it("load swallows a plain Error named AbortError (S-230)", async () => {
    mockedGet.mockRejectedValueOnce(
      Object.assign(new Error("aborted"), { name: "AbortError" }),
    );
    await useSigmaRulesStore.getState().load(new AbortController().signal);
    expect(useSigmaRulesStore.getState().status).not.toBe("error");
  });

  it("setFilter merges patches", () => {
    useSigmaRulesStore.getState().setFilter({ search: "ssh" });
    expect(useSigmaRulesStore.getState().filter.search).toBe("ssh");
    useSigmaRulesStore.getState().setFilter({ enabledOnly: true });
    const f = useSigmaRulesStore.getState().filter;
    expect(f.search).toBe("ssh");
    expect(f.enabledOnly).toBe(true);
  });

  it("select sets selectedRuleId", () => {
    useSigmaRulesStore.getState().select("rid-1");
    expect(useSigmaRulesStore.getState().selectedRuleId).toBe("rid-1");
    useSigmaRulesStore.getState().select(null);
    expect(useSigmaRulesStore.getState().selectedRuleId).toBeNull();
  });

  it("toggle optimistically updates and confirms on success", async () => {
    mockedGet.mockResolvedValueOnce({
      items: [sampleRule],
      total: 1,
      page: 1,
      limit: 100,
    });
    await useSigmaRulesStore.getState().load();
    mockedToggle.mockResolvedValueOnce({ ...sampleRule, enabled: false, yaml_source: "x" });
    await useSigmaRulesStore.getState().toggle("r1", false);
    expect(useSigmaRulesStore.getState().rules[0].enabled).toBe(false);
  });

  it("toggle reverts state on error", async () => {
    mockedGet.mockResolvedValueOnce({
      items: [sampleRule],
      total: 1,
      page: 1,
      limit: 100,
    });
    await useSigmaRulesStore.getState().load();
    mockedToggle.mockRejectedValueOnce(new Error("nope"));
    await expect(
      useSigmaRulesStore.getState().toggle("r1", false),
    ).rejects.toThrow();
    expect(useSigmaRulesStore.getState().rules[0].enabled).toBe(true);
  });

  it("reset clears rules and filter", () => {
    useSigmaRulesStore.setState({ rules: [sampleRule], total: 5 });
    useSigmaRulesStore.getState().setFilter({ search: "x" });
    useSigmaRulesStore.getState().reset();
    const s = useSigmaRulesStore.getState();
    expect(s.rules).toEqual([]);
    expect(s.total).toBe(0);
    expect(s.filter.search).toBe("");
  });
});
