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

// S-060.F2 — entity-detail chrome
describe("EntityDetail entity-type badge (S-060.F2)", () => {
  it("renders the focal entity type uppercased + tinted via entitySourceColor", () => {
    useEntityStore.setState({ selectedEntityUuid: UUID, selectedEntityType: "user", selectedEntityValue: "alice" });
    render(<EntityDetail />);
    const badge = screen.getByText("USER");
    expect(badge).toBeInTheDocument();
    // tint applied as inline style — colour itself is deterministic via entitySourceColor
    expect((badge as HTMLElement).style.backgroundColor).not.toBe("");
  });

  it("falls back to neutral '—' badge when focal type is null", () => {
    useEntityStore.setState({
      selectedEntityUuid: UUID,
      selectedEntityType: null,
      selectedEntityValue: "alice",
      events: [],
      related: [],
    });
    render(<EntityDetail />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

describe("EntityDetail copy-UUID (S-060.F2)", () => {
  it("copies the full UUID and fires success toast at SUCCESS_MS=3000", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const sonner = await import("sonner");
    const successSpy = vi.spyOn(sonner.toast, "success").mockImplementation(() => "id" as unknown as string | number);

    useEntityStore.setState({ selectedEntityUuid: UUID, selectedEntityType: "user", selectedEntityValue: "alice" });
    render(<EntityDetail />);
    fireEvent.click(screen.getByRole("button", { name: /copy entity uuid/i }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(UUID));
    expect(successSpy).toHaveBeenCalledWith("Copied UUID", expect.objectContaining({ duration: 3000 }));
    successSpy.mockRestore();
  });

  it("fires error toast at ERROR_MS=5000 on clipboard failure", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const sonner = await import("sonner");
    const errorSpy = vi.spyOn(sonner.toast, "error").mockImplementation(() => "id" as unknown as string | number);

    useEntityStore.setState({ selectedEntityUuid: UUID, selectedEntityType: "user", selectedEntityValue: "alice" });
    render(<EntityDetail />);
    fireEvent.click(screen.getByRole("button", { name: /copy entity uuid/i }));

    await waitFor(() =>
      expect(errorSpy).toHaveBeenCalledWith("Copy failed", expect.objectContaining({ duration: 5000 })),
    );
    errorSpy.mockRestore();
  });
});

describe("EntityDetail source filter (S-060.F2)", () => {
  it("renders the Source select trigger labelled 'Source'", () => {
    useEntityStore.setState({
      selectedEntityUuid: UUID,
      selectedEntityType: "user",
      selectedEntityValue: "alice",
      discoveredSourceTypes: ["auth", "syslog"],
    });
    render(<EntityDetail />);
    expect(screen.getByRole("combobox", { name: /source/i })).toBeInTheDocument();
  });
});

describe("EntityDetail severity toggle (S-060.F2)", () => {
  it("renders 7 toggle items 0..6 with aria-labels from SEVERITY_NUM_LABEL", () => {
    useEntityStore.setState({ selectedEntityUuid: UUID, selectedEntityType: "user", selectedEntityValue: "alice" });
    render(<EntityDetail />);
    expect(screen.getByLabelText("Trace")).toBeInTheDocument();
    expect(screen.getByLabelText("Informational")).toBeInTheDocument();
    expect(screen.getByLabelText("Notice")).toBeInTheDocument();
    expect(screen.getByLabelText("Warning")).toBeInTheDocument();
    expect(screen.getByLabelText("Error")).toBeInTheDocument();
    expect(screen.getByLabelText("Critical")).toBeInTheDocument();
    expect(screen.getByLabelText("Fatal")).toBeInTheDocument();
  });

  it("clicking a non-zero severity toggle calls setSeverityMin(n)", async () => {
    (api.get as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      entity_uuid: UUID,
      events: [],
      related: [],
      total: 0,
    });
    useEntityStore.setState({ selectedEntityUuid: UUID, selectedEntityType: "user", selectedEntityValue: "alice" });
    render(<EntityDetail />);
    fireEvent.click(screen.getByLabelText("Warning"));
    await waitFor(() => expect(useEntityStore.getState().severityMin).toBe(3));
  });
});

describe("EntityDetail Custom… chip stub (S-060.F2)", () => {
  it("renders disabled with title='Coming soon'", () => {
    useEntityStore.setState({ selectedEntityUuid: UUID, selectedEntityType: "user", selectedEntityValue: "alice" });
    render(<EntityDetail />);
    const chip = screen.getByRole("button", { name: /custom…/i });
    expect(chip).toBeDisabled();
    expect(chip).toHaveAttribute("aria-disabled", "true");
    expect(chip).toHaveAttribute("title", "Coming soon");
  });
});

describe("EntityDetail sizing-contract alignment (S-060.F2)", () => {
  it("no descendant uses min-h-[…] pinned heights", () => {
    useEntityStore.setState({ selectedEntityUuid: UUID, selectedEntityType: "user", selectedEntityValue: "alice" });
    const { container } = render(<EntityDetail />);
    const all = container.querySelectorAll("*");
    for (const el of Array.from(all)) {
      for (const cls of Array.from((el as HTMLElement).classList)) {
        expect(cls.startsWith("min-h-[")).toBe(false);
      }
    }
  });

  it("timeline wrapper uses h-full min-h-0 flex flex-col", () => {
    useEntityStore.setState({ selectedEntityUuid: UUID, selectedEntityType: "user", selectedEntityValue: "alice" });
    const { container } = render(<EntityDetail />);
    const wrapper = container.querySelector("div.overflow-hidden.rounded-md.border");
    expect(wrapper).not.toBeNull();
    expect(wrapper).toHaveClass("h-full");
    expect(wrapper).toHaveClass("min-h-0");
    expect(wrapper).toHaveClass("flex");
    expect(wrapper).toHaveClass("flex-col");
  });
});
