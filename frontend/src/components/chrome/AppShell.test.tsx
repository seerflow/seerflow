import { render, screen, act } from "@testing-library/react";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import type { ReactNode } from "react";
import { AppShell } from "./AppShell";
import { useThemeStore } from "@/stores/theme";
import { useAlertStore } from "@/stores/alerts";
import { useStatusStore } from "@/stores/status";
import * as wsBus from "@/lib/wsBus";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: { get: vi.fn().mockResolvedValue({ items: [] }), post: vi.fn() },
  ApiError: class ApiError extends Error {},
}));

// Heavy component mocks
vi.mock("@/components/DashboardGrid/DashboardGrid", () => ({
  DashboardGrid: () => <div data-testid="dashboard-grid">DashboardGrid</div>,
}));
vi.mock("@/components/DashboardGrid/AddWidgetMenu", () => ({
  AddWidgetMenu: () => null,
}));
vi.mock("@/components/DashboardGrid/ResetLayoutButton", () => ({
  ResetLayoutButton: () => null,
}));
vi.mock("@/components/EntityExplorer/EntityDetail", () => ({
  EntityDetail: () => <div data-testid="entity-detail">EntityDetail</div>,
}));
vi.mock("@/components/EntityExplorer/EntitySearch", () => ({
  EntitySearch: () => <div data-testid="entity-search">EntitySearch</div>,
}));
vi.mock("@/components/AttackHeatmap/AttackHeatmap", () => ({
  AttackHeatmap: () => <div data-testid="attack-heatmap">AttackHeatmap</div>,
}));
vi.mock("@/components/SigmaRules/SigmaRulesPage", () => ({
  SigmaRulesPage: () => <div data-testid="sigma-rules-page">SigmaRulesPage</div>,
}));
vi.mock("@/components/EventStream/EventStream", () => ({
  EventStream: () => <div data-testid="event-stream">EventStream</div>,
}));
vi.mock("react-grid-layout", () => ({
  Responsive: ({ children }: { children: ReactNode }) => (
    <div data-testid="rgl">{children}</div>
  ),
  WidthProvider:
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (Cmp: any) =>
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (props: any) => <Cmp {...props} width={1200} />,
}));
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

describe("AppShell", () => {
  beforeEach(() => {
    vi.stubGlobal("WebSocket", NoopWS as unknown as typeof WebSocket);
    localStorage.clear();
    document.documentElement.classList.remove("sf-light");
    window.history.replaceState(null, "", "/");
    useThemeStore.setState({ theme: "dark" });
    useAlertStore.setState({ alerts: [] });
    useStatusStore.setState({ pipelineOnline: false, uptimeLabel: "—", evPerSec: 0 });
    wsBus._clearAllForTests();
    useStatusStore.getState()._resubscribe();
    (
      globalThis as unknown as { ResizeObserver: typeof ResizeObserver }
    ).ResizeObserver = class {
      observe() {}
      disconnect() {}
      unobserve() {}
    } as unknown as typeof ResizeObserver;
  });

  afterEach(() => vi.unstubAllGlobals());

  it("renders sidebar with 'seerflow' brand text", () => {
    render(<AppShell />);
    expect(screen.getByText("seerflow")).toBeInTheDocument();
  });

  it("renders topbar with ⌘K hint", () => {
    render(<AppShell />);
    expect(screen.getByText("⌘K")).toBeInTheDocument();
  });

  it("default hash (empty) renders OverviewScreen / DashboardGrid", () => {
    render(<AppShell />);
    expect(screen.getByTestId("dashboard-grid")).toBeInTheDocument();
  });

  it("hash #/overview renders DashboardGrid", () => {
    window.history.replaceState(null, "", "/#/overview");
    render(<AppShell />);
    act(() => { window.dispatchEvent(new HashChangeEvent("hashchange")); });
    expect(screen.getByTestId("dashboard-grid")).toBeInTheDocument();
  });

  it("hash #/alerts renders AlertsScreen stub", () => {
    window.history.replaceState(null, "", "/#/alerts");
    render(<AppShell />);
    act(() => { window.dispatchEvent(new HashChangeEvent("hashchange")); });
    // "Alerts" text appears in sidebar nav + ScreenStub; use coming-soon to confirm screen rendered
    expect(screen.getByText(/coming soon/i)).toBeInTheDocument();
    // ScreenStub renders "under construction" text
    expect(screen.getByText(/under construction/i)).toBeInTheDocument();
  });

  it("legacy hash #coverage renders AttackScreen", () => {
    window.history.replaceState(null, "", "/#coverage");
    render(<AppShell />);
    act(() => { window.dispatchEvent(new HashChangeEvent("hashchange")); });
    // Need to wait for api mock
    expect(screen.getByTestId("attack-heatmap")).toBeInTheDocument();
  });

  it("legacy hash #sigma-rules renders SigmaScreen", () => {
    window.history.replaceState(null, "", "/#sigma-rules");
    render(<AppShell />);
    act(() => { window.dispatchEvent(new HashChangeEvent("hashchange")); });
    expect(screen.getByTestId("sigma-rules-page")).toBeInTheDocument();
  });

  it("ThemeToggle dark/light buttons flip .sf-light class", () => {
    render(<AppShell />);
    // start dark → click Light (wrap in act to flush zustand updates)
    act(() => { screen.getByTitle("Light").click(); });
    expect(document.documentElement.classList.contains("sf-light")).toBe(true);
    act(() => { screen.getByTitle("Dark").click(); });
    expect(document.documentElement.classList.contains("sf-light")).toBe(false);
  });

  it("DisconnectedBanner appears after WS disconnect", () => {
    vi.useFakeTimers();
    render(<AppShell />);
    act(() => { wsBus.emit({ type: "__status", status: "closed" }); });
    act(() => { vi.advanceTimersByTime(3000); });
    expect(screen.getByText(/live stream disconnected/i)).toBeInTheDocument();
    vi.useRealTimers();
  });

  it("mounts exactly one WebSocket", () => {
    const ctor = vi.fn(() => new NoopWS());
    vi.stubGlobal("WebSocket", ctor as unknown as typeof WebSocket);
    render(<AppShell />);
    expect(ctor).toHaveBeenCalledTimes(1);
  });
});

void api; // suppress unused import warning
