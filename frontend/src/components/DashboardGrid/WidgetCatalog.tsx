// Static widget registry: by design this file co-locates a wrapper component
// (EntityExplorerWidget) with non-component exports (WIDGET_CATALOG, getWidget,
// types). Splitting would require a separate file just for the inline wrapper,
// which is not worth it. HMR caveat does not apply — this is a stable registry.
/* eslint-disable react-refresh/only-export-components */
import type { ComponentType } from "react";
import type { WidgetId } from "@/stores/layout";
import { AlertFeed } from "@/components/AlertFeed/AlertFeed";
import { AnomalyTimeline } from "@/components/AnomalyTimeline/AnomalyTimeline";
import { EntityDetail } from "@/components/EntityExplorer/EntityDetail";
import { EntitySearch } from "@/components/EntityExplorer/EntitySearch";
import { EventStream } from "@/components/EventStream/EventStream";
import { AttackHeatmap } from "@/components/AttackHeatmap/AttackHeatmap";
import { SourceHealthPreview } from "@/components/DashboardGrid/placeholders/SourceHealthPreview";

export type WidgetCategory = "core" | "optional";

export interface WidgetEntry {
  id: WidgetId;
  title: string;
  category: WidgetCategory;
  Component: ComponentType;
}

// EntityExplorer was previously two sibling components; wrap for the grid.
function EntityExplorerWidget(): JSX.Element {
  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <EntitySearch />
      <div className="flex-1 min-h-0 overflow-hidden">
        <EntityDetail />
      </div>
    </div>
  );
}

export const WIDGET_CATALOG: readonly WidgetEntry[] = [
  { id: "alertFeed", title: "Alert feed", category: "core", Component: AlertFeed },
  { id: "anomalyTimeline", title: "Anomaly timeline", category: "core", Component: AnomalyTimeline },
  { id: "entityExplorer", title: "Entity explorer", category: "core", Component: EntityExplorerWidget },
  { id: "eventStream", title: "Event stream", category: "core", Component: EventStream },
  { id: "attackHeatmap", title: "ATT&CK coverage", category: "optional", Component: AttackHeatmap },
  { id: "sourceHealthPreview", title: "Source health", category: "optional", Component: SourceHealthPreview },
] as const;

export function getWidget(id: WidgetId): WidgetEntry | undefined {
  return WIDGET_CATALOG.find((w) => w.id === id);
}
