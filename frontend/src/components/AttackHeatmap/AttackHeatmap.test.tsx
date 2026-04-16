import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { AttackHeatmap } from "./AttackHeatmap";
import { useCoverageStore, type CoverageState } from "@/stores/coverage";

type StoreSelector = <T>(state: CoverageState) => T;

const mockFetch = vi.fn();

vi.mock("@/stores/coverage", () => ({
  useCoverageStore: vi.fn(),
}));

const mockCoverageData = {
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

function mockStore(state: CoverageState): void {
  vi.mocked(useCoverageStore).mockImplementation(
    ((sel: StoreSelector) => sel(state)) as unknown as typeof useCoverageStore,
  );
}

describe("AttackHeatmap", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("shows loading state", () => {
    mockStore({ data: null, loading: true, error: null, fetch: mockFetch });
    render(<AttackHeatmap />);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("shows error state", () => {
    mockStore({ data: null, loading: false, error: "network", fetch: mockFetch });
    render(<AttackHeatmap />);
    expect(screen.getByText(/network/i)).toBeInTheDocument();
  });

  it("renders all 14 tactic columns when data loaded", () => {
    mockStore({ data: mockCoverageData, loading: false, error: null, fetch: mockFetch });
    render(<AttackHeatmap />);
    // All 14 tactic headers should render from the static catalog
    expect(screen.getByText("Reconnaissance")).toBeInTheDocument();
    expect(screen.getByText("Impact")).toBeInTheDocument();
    expect(screen.getByText("Persistence")).toBeInTheDocument();
  });

  it("calls fetch on mount", () => {
    mockStore({ data: null, loading: false, error: null, fetch: mockFetch });
    render(<AttackHeatmap />);
    expect(mockFetch).toHaveBeenCalledOnce();
  });
});
