/**
 * S-318: App shell integration tests.
 *
 * These tests verify the sidebar-nav shell via the App entry point (which
 * delegates to AppShell). Heavy component mocking keeps the suite fast;
 * the chrome components (Sidebar, Topbar, AppShell) have their own focused
 * unit tests in src/components/chrome/.
 */
import { render, screen, act } from "@testing-library/react";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import App from "./App";
import { useThemeStore } from "@/stores/theme";
import { useAlertStore } from "@/stores/alerts";
import { useStatusStore } from "@/stores/status";
import { useEntityStore } from "@/stores/entity";
import * as wsBus from "@/lib/wsBus";

vi.mock("@/lib/api", () => ({
  api: { get: vi.fn().mockResolvedValue({ items: [] }), post: vi.fn() },
  ApiError: class ApiError extends Error {},
}));

// Mock heavy screen components so tests stay fast
vi.mock("@/components/AttackHeatmap/AttackHeatmap", () => ({
  AttackHeatmap: () => <div data-testid="attack-heatmap">AttackHeatmap</div>,
}));
vi.mock("@/components/SigmaRules/SigmaRulesPage", () => ({
  SigmaRulesPage: () => <div data-testid="sigma-rules-page">SigmaRulesPage</div>,
}));
vi.mock("@/screens/SigmaScreen", () => ({
  SigmaScreen: () => <div data-testid="sigma-screen">SigmaScreen</div>,
}));
vi.mock("@/components/EventStream/EventStream", () => ({
  EventStream: () => <div data-testid="event-stream">EventStream</div>,
}));
// S-320: Mock OverviewScreen to avoid heavy Overview sub-component deps
vi.mock("@/screens/OverviewScreen", () => ({
  OverviewScreen: () => <div data-testid="overview-screen">OverviewScreen</div>,
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

describe("App shell (S-318)", () => {
  beforeEach(() => {
    vi.stubGlobal("WebSocket", NoopWS as unknown as typeof WebSocket);
    localStorage.clear();
    document.documentElement.classList.remove("sf-light");
    document.documentElement.removeAttribute("data-theme");
    window.history.replaceState(null, "", "/");
    useThemeStore.setState({ theme: "dark" });
    useAlertStore.setState({ alerts: [] });
    useStatusStore.setState({ pipelineOnline: false, uptimeLabel: "—", evPerSec: 0 });
    useEntityStore.setState(useEntityStore.getInitialState());
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

  it("renders the sidebar with 'seerflow' brand text", () => {
    render(<App />);
    expect(screen.getByText("seerflow")).toBeInTheDocument();
  });

  it("renders the topbar with ⌘K", () => {
    render(<App />);
    expect(screen.getByText("⌘K")).toBeInTheDocument();
  });

  it("default hash renders OverviewScreen", () => {
    render(<App />);
    expect(screen.getByTestId("overview-screen")).toBeInTheDocument();
  });

  it("hash #/overview renders OverviewScreen", () => {
    window.history.replaceState(null, "", "/#/overview");
    render(<App />);
    act(() => {
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(screen.getByTestId("overview-screen")).toBeInTheDocument();
  });

  it("hash #/attack renders AttackScreen", () => {
    window.history.replaceState(null, "", "/#/attack");
    render(<App />);
    act(() => {
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(screen.getByTestId("attack-heatmap")).toBeInTheDocument();
  });

  it("hash #/sigma renders SigmaScreen", () => {
    window.history.replaceState(null, "", "/#/sigma");
    render(<App />);
    act(() => {
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(screen.getByTestId("sigma-screen")).toBeInTheDocument();
  });

  it("hash #/events renders EventsScreen", () => {
    window.history.replaceState(null, "", "/#/events");
    render(<App />);
    act(() => {
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(screen.getByTestId("event-stream")).toBeInTheDocument();
  });

  it("hash #/settings renders Settings coming soon", () => {
    window.history.replaceState(null, "", "/#/settings");
    render(<App />);
    act(() => {
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(screen.getByText(/coming soon/i)).toBeInTheDocument();
  });

  it("legacy #coverage hash renders AttackScreen", () => {
    window.history.replaceState(null, "", "/#coverage");
    render(<App />);
    act(() => {
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(screen.getByTestId("attack-heatmap")).toBeInTheDocument();
  });

  it("legacy #sigma-rules hash renders SigmaScreen", () => {
    window.history.replaceState(null, "", "/#sigma-rules");
    render(<App />);
    act(() => {
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(screen.getByTestId("sigma-screen")).toBeInTheDocument();
  });

  it("ThemeToggle dark/light buttons flip .sf-light class", () => {
    render(<App />);
    act(() => {
      screen.getByTitle("Light").click();
    });
    expect(document.documentElement.classList.contains("sf-light")).toBe(true);
    act(() => {
      screen.getByTitle("Dark").click();
    });
    expect(document.documentElement.classList.contains("sf-light")).toBe(false);
  });

  it("mounts exactly one WebSocket via WsProvider", () => {
    const ctor = vi.fn(() => new NoopWS());
    vi.stubGlobal("WebSocket", ctor as unknown as typeof WebSocket);
    render(<App />);
    expect(ctor).toHaveBeenCalledTimes(1);
  });
});

describe("App shell DisconnectedBanner", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", NoopWS as unknown as typeof WebSocket);
    localStorage.clear();
    document.documentElement.classList.remove("sf-light");
    window.history.replaceState(null, "", "/");
    useThemeStore.setState({ theme: "dark" });
    useAlertStore.setState({ alerts: [] });
    useStatusStore.setState({ pipelineOnline: false, uptimeLabel: "—", evPerSec: 0 });
    useEntityStore.setState(useEntityStore.getInitialState());
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
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("shows DisconnectedBanner after WS closes", () => {
    render(<App />);
    act(() => {
      wsBus.emit({ type: "__status", status: "closed" });
    });
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(screen.getByText(/live stream disconnected/i)).toBeInTheDocument();
  });

  it("DisconnectedBanner is inside the shell (not in sidebar)", () => {
    const { container } = render(<App />);
    act(() => {
      wsBus.emit({ type: "__status", status: "closed" });
    });
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    const banner = screen.getByText(/live stream disconnected/i);
    // Banner must NOT be inside the sidebar
    const sidebar = container.querySelector(
      '[style*="grid-area: sidebar"]',
    );
    if (sidebar) {
      expect(sidebar.contains(banner)).toBe(false);
    }
    expect(banner).toBeInTheDocument();
  });
});
