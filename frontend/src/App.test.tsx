import { render, screen, fireEvent, act } from "@testing-library/react";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import App from "./App";
import { useThemeStore } from "@/stores/theme";
import { api } from "@/lib/api";
import { useEntityStore } from "@/stores/entity";
import { hashHasCoverage } from "@/lib/hash";
import * as wsBus from "@/lib/wsBus";

vi.mock("@/lib/api", () => ({
  api: { get: vi.fn().mockResolvedValue({ items: [] }), post: vi.fn() },
  ApiError: class ApiError extends Error {},
}));

class NoopWS {
  readyState = 0;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  send() {}
  close() {}
}

describe("App shell", () => {
  beforeEach(() => {
    vi.stubGlobal("WebSocket", NoopWS as unknown as typeof WebSocket);
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
    // Zustand store is a module-level singleton; reset to the same
    // initial state each test sees.
    useThemeStore.setState({ theme: "light" });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("renders the Seerflow wordmark", () => {
    render(<App />);
    const wordmark = screen.getByRole("img", { name: /seerflow/i });
    expect(wordmark).toBeInTheDocument();
    expect(wordmark).toHaveAttribute("src");
  });

  it("swaps the wordmark when the theme flips", () => {
    render(<App />);
    const lightSrc = (
      screen.getByRole("img", { name: /seerflow/i }) as HTMLImageElement
    ).src;
    fireEvent.click(screen.getByRole("button", { name: /toggle theme/i }));
    const darkSrc = (
      screen.getByRole("img", { name: /seerflow/i }) as HTMLImageElement
    ).src;
    expect(darkSrc).not.toBe(lightSrc);
  });

  it("renders the main region", () => {
    const { container } = render(<App />);
    expect(container.querySelector("main")).toBeInTheDocument();
  });

  it("theme toggle button flips data-theme", () => {
    render(<App />);
    const btn = screen.getByRole("button", { name: /toggle theme/i });
    fireEvent.click(btn);
    expect(document.documentElement.dataset.theme).toBe("dark");
    fireEvent.click(btn);
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("mounts AnomalyTimeline alongside AlertFeed", async () => {
    render(<App />);
    expect(await screen.findByText("Anomaly Timeline")).toBeInTheDocument();
  });
});

describe("DisconnectedBanner dashboard mount", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", NoopWS as unknown as typeof WebSocket);
    localStorage.clear();
    window.history.replaceState(null, "", "/");
    useThemeStore.setState({ theme: "light" });
    useEntityStore.setState(useEntityStore.getInitialState());
    wsBus.clearAll();
    (globalThis as unknown as { ResizeObserver: typeof ResizeObserver }).ResizeObserver =
      class { observe() {} disconnect() {} unobserve() {} } as unknown as typeof ResizeObserver;
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("mounts DisconnectedBanner on the dashboard branch (above the grid, inside <main>)", () => {
    const { container } = render(<App />);
    act(() => { wsBus.emit({ type: "__status", status: "closed" }); });
    act(() => { vi.advanceTimersByTime(3000); });

    // Multiple elements share role="status" (SummaryBadges connection dot).
    // Filter by the banner's distinctive text to isolate the DisconnectedBanner.
    const banner = screen.getByText(/live stream disconnected/i);
    expect(banner).toBeInTheDocument();
    expect(banner.getAttribute("role")).toBe("status");

    // Must be inside <main>, confirming it is at the dashboard header,
    // not orphaned off-tree.
    const main = container.querySelector("main");
    expect(main).not.toBeNull();
    expect(main!.contains(banner)).toBe(true);
  });

  it("renders the banner OUTSIDE the AlertFeed <section>", () => {
    const { container } = render(<App />);
    act(() => { wsBus.emit({ type: "__status", status: "closed" }); });
    act(() => { vi.advanceTimersByTime(3000); });

    const banner = screen.getByText(/live stream disconnected/i);
    // AlertFeed renders a <section>; the banner (post-S-062 Phase A) must
    // not be nested inside it — it lives at the dashboard header above the
    // grid, as a sibling of the section.
    const sections = container.querySelectorAll("section");
    for (const section of sections) {
      expect(section.contains(banner)).toBe(false);
    }
  });
});

describe("hashHasCoverage", () => {
  it("returns true for #coverage", () => {
    expect(hashHasCoverage("#coverage")).toBe(true);
  });

  it("returns false for empty hash", () => {
    expect(hashHasCoverage("")).toBe(false);
  });

  it("returns false for entity hash", () => {
    expect(hashHasCoverage("#entity=abc")).toBe(false);
  });
});

describe("App hash routing", () => {
  beforeEach(() => {
    vi.stubGlobal("WebSocket", NoopWS as unknown as typeof WebSocket);
    window.history.replaceState(null, "", "/");
    useEntityStore.setState(useEntityStore.getInitialState());
    useThemeStore.setState({ theme: "light" });
    (globalThis as unknown as { ResizeObserver: typeof ResizeObserver }).ResizeObserver =
      class { observe() {} disconnect() {} unobserve() {} } as unknown as typeof ResizeObserver;
  });
  afterEach(() => vi.unstubAllGlobals());

  it("renders dashboard when hash empty", () => {
    render(<App />);
    expect(screen.getByRole("combobox", { name: /search entities/i })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /entity detail/i })).toBeNull();
  });

  it("switches to EntityDetail when hash includes entity=<uuid>", async () => {
    (api.get as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      entity_uuid: "u", events: [], related: [], total: 0,
    });
    window.history.replaceState(null, "", "/#entity=11111111-2222-3333-4444-555555555555");
    render(<App />);
    await act(async () => { window.dispatchEvent(new HashChangeEvent("hashchange")); });
    expect(await screen.findByLabelText(/entity detail/i)).toBeInTheDocument();
  });
});
