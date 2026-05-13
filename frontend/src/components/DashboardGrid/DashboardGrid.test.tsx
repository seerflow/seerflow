import { render, screen, fireEvent, act } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import type { ReactNode } from "react";
import { useLayoutStore } from "@/stores/layout";

// jsdom does not measure, so react-grid-layout's Responsive/WidthProvider
// cannot compute columns. Mock the module: render children directly and
// stash the onLayoutChange callback on globalThis so Test C can invoke it.
vi.mock("react-grid-layout", () => {
  type ResponsiveProps = {
    children: ReactNode;
    onLayoutChange?: (current: unknown, all: unknown) => void;
  };
  return {
    Responsive: ({ children, onLayoutChange }: ResponsiveProps) => {
      (globalThis as unknown as { __rglOnLayoutChange?: typeof onLayoutChange }).__rglOnLayoutChange =
        onLayoutChange;
      return <div data-testid="rgl">{children}</div>;
    },
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

// Replace real widgets (which require WsProvider, API clients, etc.) with
// trivial stubs. DashboardGrid's job is composing the catalog through the grid;
// verifying real widget internals belongs to their own test files.
vi.mock("@/components/DashboardGrid/WidgetCatalog", () => {
  const make = (title: string) => () => <div>{title} body</div>;
  const CATALOG = [
    { id: "alertFeed", title: "Alert feed", category: "core", Component: make("Alert feed") },
    { id: "anomalyTimeline", title: "Anomaly timeline", category: "core", Component: make("Anomaly timeline") },
    { id: "entityExplorer", title: "Entity explorer", category: "core", Component: make("Entity explorer") },
    { id: "eventStream", title: "Event stream", category: "core", Component: make("Event stream") },
    { id: "attackHeatmap", title: "ATT&CK coverage", category: "optional", Component: make("ATT&CK coverage") },
    { id: "sourceHealthPreview", title: "Source health", category: "optional", Component: make("Source health") },
  ] as const;
  return {
    WIDGET_CATALOG: CATALOG,
    getWidget: (id: string) => CATALOG.find((w) => w.id === id),
  };
});

import { DashboardGrid } from "./DashboardGrid";

beforeEach(() => {
  useLayoutStore.getState().resetToDefault();
  (globalThis as unknown as { __rglOnLayoutChange?: unknown }).__rglOnLayoutChange = undefined;
});

describe("DashboardGrid", () => {
  it("renders the four default widget titles via WIDGET_CATALOG", () => {
    render(<DashboardGrid />);
    expect(screen.getByText("Alert feed")).toBeInTheDocument();
    expect(screen.getByText("Anomaly timeline")).toBeInTheDocument();
    expect(screen.getByText("Entity explorer")).toBeInTheDocument();
    expect(screen.getByText("Event stream")).toBeInTheDocument();
  });

  it("shows EmptyGridHint (no RGL wrapper) when widgets is empty", () => {
    useLayoutStore.setState({ widgets: [] });
    render(<DashboardGrid />);
    expect(screen.getByText(/Your dashboard is empty/i)).toBeInTheDocument();
    expect(screen.queryByTestId("rgl")).toBeNull();
  });

  it("onLayoutChange from RGL propagates into useLayoutStore.setLayouts", () => {
    render(<DashboardGrid />);
    const onLayoutChange = (
      globalThis as unknown as {
        __rglOnLayoutChange?: (current: unknown, all: unknown) => void;
      }
    ).__rglOnLayoutChange;
    expect(onLayoutChange).toBeTypeOf("function");

    const next = {
      lg: [{ i: "alertFeed", x: 1, y: 2, w: 3, h: 4 }],
      md: [],
      sm: [],
    };
    act(() => {
      onLayoutChange!({}, next);
    });
    expect(useLayoutStore.getState().layouts).toEqual(next);
  });

  it("clicking a widget's × removes it from the store", () => {
    render(<DashboardGrid />);
    fireEvent.click(screen.getByRole("button", { name: /Remove Alert feed/i }));
    expect(useLayoutStore.getState().widgets).not.toContain("alertFeed");
  });

  it("tolerates unknown widget ids by skipping them without throwing", () => {
    useLayoutStore.setState({
      widgets: ["bogus" as never, "alertFeed"],
    });
    expect(() => render(<DashboardGrid />)).not.toThrow();
    expect(screen.getByText("Alert feed")).toBeInTheDocument();
    // Only one known widget rendered means exactly one Drag/Remove button pair.
    expect(screen.getAllByRole("button", { name: /Drag .*/i })).toHaveLength(1);
  });
});
