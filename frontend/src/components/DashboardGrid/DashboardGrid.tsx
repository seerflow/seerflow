import { useCallback } from "react";
import { Responsive, WidthProvider, type Layouts } from "react-grid-layout";
import {
  useLayoutStore,
  type Breakpoint,
  type LayoutsByBreakpoint,
} from "@/stores/layout";
import { getWidget } from "@/components/DashboardGrid/WidgetCatalog";
import { WidgetFrame } from "@/components/DashboardGrid/WidgetFrame";
import { EmptyGridHint } from "@/components/DashboardGrid/EmptyGridHint";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";

const ResponsiveGrid = WidthProvider(Responsive);
const COLS: Record<Breakpoint, number> = { lg: 12, md: 10, sm: 6 };
const BREAKPOINTS: Record<Breakpoint, number> = { lg: 1280, md: 768, sm: 0 };

export function DashboardGrid(): JSX.Element {
  const widgets = useLayoutStore((s) => s.widgets);
  const layouts = useLayoutStore((s) => s.layouts) as unknown as Layouts;
  const setLayouts = useLayoutStore((s) => s.setLayouts);
  const removeWidget = useLayoutStore((s) => s.removeWidget);

  const onLayoutChange = useCallback(
    (_: unknown, all: Layouts) => {
      setLayouts(all as unknown as LayoutsByBreakpoint);
    },
    [setLayouts],
  );

  if (widgets.length === 0) return <EmptyGridHint />;

  return (
    <ResponsiveGrid
      layouts={layouts}
      breakpoints={BREAKPOINTS}
      cols={COLS}
      rowHeight={64}
      margin={[12, 12]}
      draggableHandle=".widget-drag-handle"
      compactType="vertical"
      isDraggable
      isResizable
      onLayoutChange={onLayoutChange}
    >
      {widgets.map((id) => {
        const entry = getWidget(id);
        if (!entry) return null;
        const { Component } = entry;
        return (
          <div key={id}>
            <WidgetFrame title={entry.title} onRemove={() => removeWidget(id)}>
              <Component />
            </WidgetFrame>
          </div>
        );
      })}
    </ResponsiveGrid>
  );
}
