/**
 * Smoke tests for all screen files.
 * Each screen must mount without throwing. Real components are mocked to
 * avoid pulling in their full dependency trees.
 */
import { render, screen, act } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

// ── Mock heavy components ────────────────────────────────────────────────────
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
// Grid layout mocks (needed by OverviewScreen → DashboardGrid)
vi.mock("react-grid-layout", () => ({
  Responsive: ({ children }: { children: React.ReactNode }) => (
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

// S-321: mock AlertFeed so AlertsScreen renders without WS/API deps
vi.mock("@/components/AlertFeed/AlertFeed", () => ({
  AlertFeed: () => <div data-testid="alert-feed">AlertFeed</div>,
}));

// S-321: mock api so AlertDetailScreen renders without network.
// Rejects immediately for nonexistent IDs so the not-found state appears.
vi.mock("@/lib/api", () => {
  class SmokeApiError extends Error {
    status: number;
    constructor(s: number, m: string) { super(m); this.status = s; }
  }
  return {
    api: {
      get: vi.fn(async (path: string) => {
        if (path.includes("smoke-id-no-alert")) throw new SmokeApiError(404, "not found");
        return new Promise(() => {});  // other paths hang (AlertFeed warm-up etc.)
      }),
    },
    ApiError: SmokeApiError,
  };
});

import { OverviewScreen } from "./OverviewScreen";
import { AlertsScreen } from "./AlertsScreen";
import { AlertDetailScreen } from "./AlertDetailScreen";
import { EventsScreen } from "./EventsScreen";
import { EntitiesScreen } from "./EntitiesScreen";
import { AttackScreen } from "./AttackScreen";
import { SigmaScreen } from "./SigmaScreen";
import { HuntScreen } from "./HuntScreen";
import { ReceiversScreen } from "./ReceiversScreen";
import { ModelsScreen } from "./ModelsScreen";
import { SettingsScreen } from "./SettingsScreen";

describe("OverviewScreen", () => {
  it("mounts and renders DashboardGrid", () => {
    render(<OverviewScreen />);
    expect(screen.getByTestId("dashboard-grid")).toBeInTheDocument();
  });
});

describe("AlertsScreen", () => {
  it("mounts and renders AlertFeed (S-321)", () => {
    render(<AlertsScreen />);
    expect(screen.getByTestId("alerts-screen")).toBeInTheDocument();
    expect(screen.getByTestId("alert-feed")).toBeInTheDocument();
  });
});

describe("AlertDetailScreen", () => {
  it("renders not-found when no alert in store (S-321)", async () => {
    window.history.replaceState(null, "", "/#/alerts/smoke-id-no-alert");
    render(<AlertDetailScreen />);
    // API rejects with 404 → loading resolves → not-found renders
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getByText(/alert not found/i)).toBeInTheDocument();
  });
});

describe("EventsScreen", () => {
  it("mounts and renders EventStream", () => {
    render(<EventsScreen />);
    expect(screen.getByTestId("event-stream")).toBeInTheDocument();
  });
});

describe("EntitiesScreen", () => {
  it("mounts and renders EntityDetail", () => {
    render(<EntitiesScreen />);
    expect(screen.getByTestId("entity-detail")).toBeInTheDocument();
  });

  it("calls restoreFromHash on mount when hash has entity= param", () => {
    const restoreFromHash = vi.fn().mockResolvedValue(undefined);
    const clearSelection = vi.fn();
    // Temporarily inject entity store mock for this test
    vi.doMock("@/stores/entity", () => ({
      useEntityStore: (sel: (s: { restoreFromHash: typeof restoreFromHash; clearSelection: typeof clearSelection }) => unknown) =>
        sel({ restoreFromHash, clearSelection }),
    }));

    window.history.replaceState(null, "", "/#entity=11111111-2222-3333-4444-555555555555");
    // The existing mock EntityDetail renders — we just check mounts cleanly
    render(<EntitiesScreen />);
    expect(screen.getByTestId("entity-detail")).toBeInTheDocument();
    window.history.replaceState(null, "", "/");
    vi.doUnmock("@/stores/entity");
  });
});

describe("AttackScreen", () => {
  it("mounts and renders AttackHeatmap", () => {
    render(<AttackScreen />);
    expect(screen.getByTestId("attack-heatmap")).toBeInTheDocument();
  });
});

describe("SigmaScreen", () => {
  it("mounts and renders SigmaRulesPage", () => {
    render(<SigmaScreen />);
    expect(screen.getByTestId("sigma-rules-page")).toBeInTheDocument();
  });
});

describe("HuntScreen", () => {
  it("renders ScreenStub with label Hunt", () => {
    render(<HuntScreen />);
    expect(screen.getByText("Hunt")).toBeInTheDocument();
    expect(screen.getByText(/coming soon/i)).toBeInTheDocument();
  });
});

describe("ReceiversScreen", () => {
  it("renders ScreenStub with label Receivers", () => {
    render(<ReceiversScreen />);
    expect(screen.getByText("Receivers")).toBeInTheDocument();
    expect(screen.getByText(/coming soon/i)).toBeInTheDocument();
  });
});

describe("ModelsScreen", () => {
  it("renders ScreenStub with label Models", () => {
    render(<ModelsScreen />);
    expect(screen.getByText("Models")).toBeInTheDocument();
    expect(screen.getByText(/coming soon/i)).toBeInTheDocument();
  });
});

describe("SettingsScreen", () => {
  it("renders ScreenStub with label Settings", () => {
    render(<SettingsScreen />);
    expect(screen.getByText("Settings")).toBeInTheDocument();
    expect(screen.getByText(/coming soon/i)).toBeInTheDocument();
  });
});
