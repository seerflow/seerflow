import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { AttackHeatmap } from "./AttackHeatmap";
import { useCoverageStore, type CoverageState } from "@/stores/coverage";
import { useDrilldownStore } from "@/stores/drilldown";

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(),
  },
}));

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
      tactic: "execution",
      tactic_display_name: "Execution (TA0002)",
      techniques: [
        { tactic: "execution", technique: "T1053", rule_count: 2, alert_count: 1, covered: true, detected: true, rule_names: ["sched_task", "crontab"] },
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

function renderHeatmapWithSampleData() {
  mockStore({ data: mockCoverageData, loading: false, error: null, fetch: mockFetch });
  return render(<AttackHeatmap />);
}

describe("AttackHeatmap", () => {
  beforeEach(async () => {
    mockFetch.mockReset();
    const { api } = await import("@/lib/api");
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
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

  it("renders the outermost container with flex h-full min-h-0 flex-col on the happy path", () => {
    mockStore({ data: mockCoverageData, loading: false, error: null, fetch: mockFetch });
    const { container } = render(<AttackHeatmap />);
    const outer = container.firstElementChild as HTMLElement;
    expect(outer).not.toBeNull();
    expect(outer.className).toMatch(/\bflex\b/);
    expect(outer.className).toMatch(/\bh-full\b/);
    expect(outer.className).toMatch(/\bmin-h-0\b/);
    expect(outer.className).toMatch(/\bflex-col\b/);
  });

  it("loading state also fills its parent (h-full min-h-0)", () => {
    mockStore({ data: null, loading: true, error: null, fetch: mockFetch });
    const { container } = render(<AttackHeatmap />);
    const outer = container.firstElementChild as HTMLElement;
    expect(outer.className).toMatch(/\bh-full\b/);
    expect(outer.className).toMatch(/\bmin-h-0\b/);
    expect(outer.className).not.toMatch(/min-h-\[/);
  });

  // ── New header band tests (RED until Task 8 impl) ──

  it("renders 'Coverage heatmap' heading when data loaded", () => {
    mockStore({ data: mockCoverageData, loading: false, error: null, fetch: mockFetch });
    render(<AttackHeatmap />);
    expect(screen.getByText("Coverage heatmap")).toBeInTheDocument();
  });

  it("renders intensity legend with 5 swatches when data loaded", () => {
    mockStore({ data: mockCoverageData, loading: false, error: null, fetch: mockFetch });
    const { container } = render(<AttackHeatmap />);
    const swatches = container.querySelectorAll("[data-intensity-swatch]");
    expect(swatches).toHaveLength(5);
  });

  it("renders tactic count in subtitle when data loaded", () => {
    mockStore({ data: mockCoverageData, loading: false, error: null, fetch: mockFetch });
    render(<AttackHeatmap />);
    // Catalog has 14 tactics; use regex to stay robust
    expect(screen.getByText(/\d+ tactics/)).toBeInTheDocument();
  });

  it("renders sigma rule count in subtitle", () => {
    mockStore({ data: mockCoverageData, loading: false, error: null, fetch: mockFetch });
    render(<AttackHeatmap />);
    // mockCoverageData has total_rules_with_attack_tags: 2
    expect(screen.getByText(/2 sigma rules/)).toBeInTheDocument();
  });

  // ── S-346 brand-token migrations ──

  it("S-346 loading container uses brand --text-3 token (not text-zinc-500)", () => {
    mockStore({ data: null, loading: true, error: null, fetch: mockFetch });
    const { container } = render(<AttackHeatmap />);
    const outer = container.firstElementChild as HTMLElement;
    expect(outer.style.color).toBe("var(--text-3)");
    expect(outer.className).not.toMatch(/text-zinc-\d+/);
  });

  it("S-346 'no coverage data' container uses brand --text-3 token", () => {
    mockStore({ data: null, loading: false, error: null, fetch: mockFetch });
    const { container } = render(<AttackHeatmap />);
    const outer = container.firstElementChild as HTMLElement;
    expect(outer.style.color).toBe("var(--text-3)");
    expect(outer.className).not.toMatch(/text-zinc-\d+/);
  });
});

describe("AttackHeatmap click-to-drill", () => {
  beforeEach(async () => {
    useDrilldownStore.getState().close();
    const { api } = await import("@/lib/api");
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
  });

  it("clicking a covered technique cell opens the drilldown panel", async () => {
    renderHeatmapWithSampleData();
    const cells = await screen.findAllByRole("button", { name: /T1053/ });
    const coveredCell = cells.find((c) => c.getAttribute("aria-label")?.includes("Detected"))!;
    fireEvent.click(coveredCell);
    await waitFor(() =>
      expect(useDrilldownStore.getState().openCell).toEqual({
        tactic: "execution",
        technique: "T1053",
      }),
    );
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });
});
