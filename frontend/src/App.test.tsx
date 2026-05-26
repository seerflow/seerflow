import { render, screen, fireEvent, act } from "@testing-library/react";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import type { ReactNode } from "react";
import App from "./App";
import { useThemeStore } from "@/stores/theme";
import { api } from "@/lib/api";
import { useEntityStore } from "@/stores/entity";
import { useLayoutStore } from "@/stores/layout";
import { hashHasCoverage } from "@/lib/hash";
import * as wsBus from "@/lib/wsBus";

vi.mock("@/lib/api", () => ({
  api: { get: vi.fn().mockResolvedValue({ items: [] }), post: vi.fn() },
  ApiError: class ApiError extends Error {},
}));

// jsdom does not measure, so react-grid-layout's WidthProvider cannot compute
// columns and would skip rendering its children. Replace Responsive /
// WidthProvider with passthrough components so the real WidgetCatalog widgets
// mount and can be asserted against directly.
vi.mock("react-grid-layout", () => {
  type ResponsiveProps = { children: ReactNode };
  return {
    Responsive: ({ children }: ResponsiveProps) => (
      <div data-testid="rgl">{children}</div>
    ),
    WidthProvider:
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (Cmp: any) =>
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (props: any) => <Cmp {...props} width={1200} />,
  };
});

// CSS imports are side-effect only; jsdom does not need them.
vi.mock("react-grid-layout/css/styles.css", () => ({}));
vi.mock("react-resizable/css/styles.css", () => ({}));

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
    // Clean up both old (data-theme) and new (.sf-light) theme mechanisms.
    document.documentElement.removeAttribute("data-theme");
    document.documentElement.classList.remove("sf-light");
    // Zustand stores are module-level singletons; reset each test so the
    // layout-grid + theme start from defaults.
    useThemeStore.setState({ theme: "light" });
    useLayoutStore.getState().resetToDefault();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("renders the Seerflow wordmark", () => {
    render(<App />);
    const wordmark = screen.getByRole("img", { name: /seerflow/i });
    expect(wordmark).toBeInTheDocument();
    expect(wordmark).toHaveAttribute("src");
  });

  it("swaps the wordmark when the theme flips", () => {
    // Start in light (beforeEach seeds theme="light")
    document.documentElement.classList.add("sf-light");
    render(<App />);
    const lightSrc = (
      screen.getByRole("img", { name: /seerflow/i }) as HTMLImageElement
    ).src;
    // Click "Dark" button in the ThemeToggle pill
    fireEvent.click(screen.getByTitle("Dark"));
    const darkSrc = (
      screen.getByRole("img", { name: /seerflow/i }) as HTMLImageElement
    ).src;
    expect(darkSrc).not.toBe(lightSrc);
  });

  it("renders the main region", () => {
    const { container } = render(<App />);
    expect(container.querySelector("main")).toBeInTheDocument();
  });

  it("ThemeToggle dark/light buttons flip .sf-light class on <html>", () => {
    // Start in light (beforeEach seeds theme="light")
    document.documentElement.classList.add("sf-light");
    render(<App />);
    // light → dark: sf-light removed
    fireEvent.click(screen.getByTitle("Dark"));
    expect(document.documentElement.classList.contains("sf-light")).toBe(false);
    // dark → light: sf-light added
    fireEvent.click(screen.getByTitle("Light"));
    expect(document.documentElement.classList.contains("sf-light")).toBe(true);
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
    document.documentElement.classList.remove("sf-light");
    window.history.replaceState(null, "", "/");
    useThemeStore.setState({ theme: "light" });
    useEntityStore.setState(useEntityStore.getInitialState());
    useLayoutStore.getState().resetToDefault();
    wsBus._clearAllForTests();
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
    localStorage.clear();
    window.history.replaceState(null, "", "/");
    useEntityStore.setState(useEntityStore.getInitialState());
    useThemeStore.setState({ theme: "light" });
    useLayoutStore.getState().resetToDefault();
    (globalThis as unknown as { ResizeObserver: typeof ResizeObserver }).ResizeObserver =
      class { observe() {} disconnect() {} unobserve() {} } as unknown as typeof ResizeObserver;
  });
  afterEach(() => vi.unstubAllGlobals());

  it("renders dashboard when hash empty", () => {
    render(<App />);
    // The header hosts an EntitySearch combobox; the EntityExplorer widget
    // inside DashboardGrid also mounts one, so at least one must exist and
    // the EntityDetail branch must NOT be active.
    expect(
      screen.getAllByRole("combobox", { name: /search entities/i }).length,
    ).toBeGreaterThanOrEqual(1);
    expect(screen.queryByRole("region", { name: /entity detail/i })).toBeNull();
  });

  it("switches to EntityDetail when hash includes entity=<uuid>", async () => {
    (api.get as unknown as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes("/risk-history")) return Promise.resolve({ items: [] });
      return Promise.resolve({ entity_uuid: "u", events: [], related: [], total: 0 });
    });
    window.history.replaceState(null, "", "/#entity=11111111-2222-3333-4444-555555555555");
    render(<App />);
    await act(async () => { window.dispatchEvent(new HashChangeEvent("hashchange")); });
    expect(await screen.findByLabelText(/entity detail/i)).toBeInTheDocument();
  });

  it("renders AttackHeatmap when hash is #coverage", async () => {
    (api.get as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      tactics: [],
      summary: { total_rules_with_attack_tags: 0, total_alerts_matched: 0 },
      window_since: "2026-01-01T00:00:00Z",
      window_until: "2026-01-02T00:00:00Z",
    });
    window.history.replaceState(null, "", "/#coverage");
    render(<App />);
    await act(async () => { window.dispatchEvent(new HashChangeEvent("hashchange")); });
    expect(await screen.findByText(/ATT&CK Coverage Matrix/i)).toBeInTheDocument();
  });
});

describe("S-062C App shell", () => {
  beforeEach(() => {
    vi.stubGlobal("WebSocket", NoopWS as unknown as typeof WebSocket);
    localStorage.clear();
    window.history.replaceState(null, "", "/");
    useThemeStore.setState({ theme: "light" });
    useEntityStore.setState(useEntityStore.getInitialState());
    useLayoutStore.getState().resetToDefault();
    wsBus._clearAllForTests();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("renders all four default widget titles via DashboardGrid", async () => {
    render(<App />);
    // WidgetFrame titles (exact case) from the WidgetCatalog.
    expect(await screen.findByText("Alert feed")).toBeInTheDocument();
    expect(screen.getByText("Anomaly timeline")).toBeInTheDocument();
    expect(screen.getByText("Entity explorer")).toBeInTheDocument();
    expect(screen.getByText("Event stream")).toBeInTheDocument();
  });

  it("exposes Add widget + Reset layout controls in the header", () => {
    render(<App />);
    expect(screen.getByRole("button", { name: /add widget/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reset layout/i })).toBeInTheDocument();
  });

  it("mounts exactly one WebSocket via WsProvider", () => {
    const ctor = vi.fn(() => new NoopWS());
    vi.stubGlobal("WebSocket", ctor as unknown as typeof WebSocket);
    render(<App />);
    expect(ctor).toHaveBeenCalledTimes(1);
  });
});

describe("S-062C banner placement", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", NoopWS as unknown as typeof WebSocket);
    localStorage.clear();
    window.history.replaceState(null, "", "/");
    useThemeStore.setState({ theme: "light" });
    useEntityStore.setState(useEntityStore.getInitialState());
    useLayoutStore.getState().resetToDefault();
    wsBus._clearAllForTests();
    (globalThis as unknown as { ResizeObserver: typeof ResizeObserver }).ResizeObserver =
      class { observe() {} disconnect() {} unobserve() {} } as unknown as typeof ResizeObserver;
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("DisconnectedBanner is a sibling (not descendant) of the body wrapper", () => {
    const { container } = render(<App />);
    act(() => { wsBus.emit({ type: "__status", status: "closed" }); });
    act(() => { vi.advanceTimersByTime(3000); });
    const banner = screen.getByText(/live stream disconnected/i);
    const body = container.querySelector(".flex-1.min-h-0");
    expect(body).not.toBeNull();
    expect(body!.contains(banner)).toBe(false);
  });
});
