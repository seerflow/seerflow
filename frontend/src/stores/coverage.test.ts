import { describe, it, expect, vi, beforeEach } from "vitest";
import { useCoverageStore } from "./coverage";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(),
  },
}));

const mockedGet = api.get as unknown as ReturnType<typeof vi.fn>;

const mockResponse = {
  window_since: "2026-03-16T00:00:00+00:00",
  window_until: "2026-04-15T00:00:00+00:00",
  tactics: [
    {
      tactic: "persistence",
      tactic_display_name: "Persistence (TA0003)",
      techniques: [
        { tactic: "persistence", technique: "T1053", rule_count: 2, alert_count: 1, covered: true, detected: true, rule_names: ["sched_task", "crontab"] },
      ],
    },
  ],
  summary: { total_techniques_covered: 1, total_techniques_detected: 1, total_rules_with_attack_tags: 2, total_alerts_matched: 1 },
};

describe("useCoverageStore", () => {
  beforeEach(() => {
    mockedGet.mockReset();
    useCoverageStore.setState({ data: null, loading: false, error: null });
  });

  it("starts with null data", () => {
    expect(useCoverageStore.getState().data).toBeNull();
  });

  it("fetch sets loading then populates data", async () => {
    mockedGet.mockResolvedValue(mockResponse);
    const store = useCoverageStore.getState();
    await store.fetch();
    const state = useCoverageStore.getState();
    expect(state.loading).toBe(false);
    expect(state.data).toEqual(mockResponse);
    expect(state.error).toBeNull();
  });

  it("fetch sets error on failure", async () => {
    mockedGet.mockRejectedValueOnce(new Error("network"));
    await useCoverageStore.getState().fetch();
    const state = useCoverageStore.getState();
    expect(state.error).toBe("network");
    expect(state.data).toBeNull();
  });
});
