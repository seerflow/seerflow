import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { useEntityStore } from "@/stores/entity";
import { api } from "@/lib/api";
import { EntityDetail } from "./EntityDetail";

const UUID = "11111111-2222-3333-4444-555555555555";

vi.mock("@/lib/api", () => ({
  api: { get: vi.fn() },
  ApiError: class extends Error { constructor(public status: number, msg: string) { super(msg); } },
}));

beforeEach(() => {
  (api.get as unknown as ReturnType<typeof vi.fn>).mockReset();
  useEntityStore.setState(useEntityStore.getInitialState());
  (globalThis as unknown as { ResizeObserver: typeof ResizeObserver }).ResizeObserver =
    class { observe() {} disconnect() {} unobserve() {} } as unknown as typeof ResizeObserver;
});

describe("EntityDetail", () => {
  it("shows loading skeleton on first mount", () => {
    (api.get as unknown as ReturnType<typeof vi.fn>).mockImplementation(() => new Promise(() => {}));
    useEntityStore.setState({ selectedEntityUuid: UUID, loading: "loading-detail" });
    render(<EntityDetail />);
    expect(screen.getByRole("status", { name: /loading/i })).toBeInTheDocument();
  });

  it("shows range chips, active chip highlighted", () => {
    useEntityStore.setState({ selectedEntityUuid: UUID, range: "6h" });
    render(<EntityDetail />);
    const chip = screen.getByRole("button", { name: "6h" });
    expect(chip).toHaveAttribute("aria-pressed", "true");
  });

  it("click on range chip calls store.setRange", async () => {
    (api.get as unknown as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes("/risk-history")) return Promise.resolve({ items: [] });
      return Promise.resolve({ entity_uuid: UUID, events: [], related: [], total: 0 });
    });
    useEntityStore.setState({ selectedEntityUuid: UUID, range: "24h" });
    render(<EntityDetail />);
    fireEvent.click(screen.getByRole("button", { name: "1h" }));
    await waitFor(() => expect(useEntityStore.getState().range).toBe("1h"));
  });

  it("outer container uses h-full min-h-0 flex flex-col (no fixed pixel height)", () => {
    useEntityStore.setState({ selectedEntityUuid: UUID });
    render(<EntityDetail />);
    const section = screen.getByRole("region", { name: /entity detail/i });
    expect(section.className).toMatch(/\bh-full\b/);
    expect(section.className).toMatch(/\bmin-h-0\b/);
    expect(section.className).toMatch(/\bflex\b/);
    expect(section.className).toMatch(/\bflex-col\b/);
  });
});

describe("EntityDetail risk sparkline (S-060.F1)", () => {
  it("does not render the interim disclosure title", () => {
    useEntityStore.setState({
      selectedEntityUuid: "11111111-1111-1111-1111-111111111111",
      selectedEntityValue: "alice",
      selectedEntityType: "user",
      range: "1h",
      events: [],
      related: [],
      riskHistory: [],
      riskHistoryLoading: false,
      riskHistoryError: null,
    });
    render(<EntityDetail />);
    expect(
      document.querySelector("[title*='Derived from current alert feed']"),
    ).toBeNull();
    expect(screen.queryByText(/^Risk \d+$/)).not.toBeInTheDocument();
  });

  it("renders the sparkline empty-state when history is all zero", () => {
    useEntityStore.setState({
      selectedEntityUuid: "11111111-1111-1111-1111-111111111111",
      selectedEntityValue: "alice",
      selectedEntityType: "user",
      range: "1h",
      events: [],
      related: [],
      riskHistory: [
        { bucket_start_ns: "0", points: 0, alert_count: 0, top_rule_name: "" },
      ],
      riskHistoryLoading: false,
      riskHistoryError: null,
    });
    render(<EntityDetail />);
    expect(
      screen.getByText(/No risk signals for this entity/i),
    ).toBeInTheDocument();
  });
});
