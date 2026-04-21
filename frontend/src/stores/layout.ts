import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import * as v from "valibot";
import { logger } from "@/lib/logger";

export type WidgetId =
  | "alertFeed"
  | "anomalyTimeline"
  | "entityExplorer"
  | "eventStream"
  | "attackHeatmap"
  | "sourceHealthPreview";

export const ALL_WIDGET_IDS: readonly WidgetId[] = [
  "alertFeed",
  "anomalyTimeline",
  "entityExplorer",
  "eventStream",
  "attackHeatmap",
  "sourceHealthPreview",
] as const;

export const DEFAULT_WIDGETS: readonly WidgetId[] = [
  "alertFeed",
  "anomalyTimeline",
  "entityExplorer",
  "eventStream",
] as const;

export interface GridItem {
  i: string;
  x: number;
  y: number;
  w: number;
  h: number;
  minW?: number;
  minH?: number;
}
export type Breakpoint = "lg" | "md" | "sm";
export type LayoutsByBreakpoint = Record<Breakpoint, GridItem[]>;

export const DEFAULT_LAYOUTS: LayoutsByBreakpoint = {
  lg: [
    { i: "alertFeed", x: 0, y: 0, w: 6, h: 8, minW: 4, minH: 4 },
    { i: "anomalyTimeline", x: 6, y: 0, w: 6, h: 8, minW: 4, minH: 4 },
    { i: "entityExplorer", x: 0, y: 8, w: 6, h: 6, minW: 4, minH: 4 },
    { i: "eventStream", x: 6, y: 8, w: 6, h: 6, minW: 4, minH: 4 },
  ],
  md: [
    { i: "alertFeed", x: 0, y: 0, w: 5, h: 8, minW: 4, minH: 4 },
    { i: "anomalyTimeline", x: 5, y: 0, w: 5, h: 8, minW: 4, minH: 4 },
    { i: "entityExplorer", x: 0, y: 8, w: 5, h: 6, minW: 4, minH: 4 },
    { i: "eventStream", x: 5, y: 8, w: 5, h: 6, minW: 4, minH: 4 },
  ],
  sm: [
    { i: "alertFeed", x: 0, y: 0, w: 6, h: 8, minW: 4, minH: 4 },
    { i: "anomalyTimeline", x: 0, y: 8, w: 6, h: 8, minW: 4, minH: 4 },
    { i: "entityExplorer", x: 0, y: 16, w: 6, h: 6, minW: 4, minH: 4 },
    { i: "eventStream", x: 0, y: 22, w: 6, h: 6, minW: 4, minH: 4 },
  ],
};

const GridItemSchema = v.object({
  i: v.string(),
  x: v.number(),
  y: v.number(),
  w: v.pipe(v.number(), v.minValue(1)),
  h: v.pipe(v.number(), v.minValue(1)),
  minW: v.optional(v.number()),
  minH: v.optional(v.number()),
});
const LayoutsSchema = v.object({
  lg: v.array(GridItemSchema),
  md: v.array(GridItemSchema),
  sm: v.array(GridItemSchema),
});
const StateSchema = v.object({
  version: v.literal(1),
  widgets: v.array(v.string()),
  layouts: LayoutsSchema,
});

export const LAYOUT_STORAGE_KEY = "seerflow.dashboard.layout.v1";

interface LayoutState {
  version: 1;
  widgets: WidgetId[];
  layouts: LayoutsByBreakpoint;
  addWidget: (id: WidgetId) => void;
  removeWidget: (id: WidgetId) => void;
  setLayouts: (layouts: LayoutsByBreakpoint) => void;
  resetToDefault: () => void;
}

function cleanUnknowns(widgets: string[]): WidgetId[] {
  const known = new Set<string>(ALL_WIDGET_IDS);
  const kept = widgets.filter((w): w is WidgetId => known.has(w));
  if (kept.length !== widgets.length) {
    logger.warn("layout rehydrate: dropping unknown widget ids", {
      dropped: widgets.filter((w) => !known.has(w)),
    });
  }
  return kept;
}

export const useLayoutStore = create<LayoutState>()(
  persist(
    (set) => ({
      version: 1,
      widgets: [...DEFAULT_WIDGETS],
      layouts: JSON.parse(JSON.stringify(DEFAULT_LAYOUTS)) as LayoutsByBreakpoint,

      addWidget: (id) =>
        set((s) =>
          s.widgets.includes(id) ? s : { ...s, widgets: [...s.widgets, id] },
        ),

      removeWidget: (id) =>
        set((s) => ({
          ...s,
          widgets: s.widgets.filter((w) => w !== id),
          layouts: {
            lg: s.layouts.lg.filter((l) => l.i !== id),
            md: s.layouts.md.filter((l) => l.i !== id),
            sm: s.layouts.sm.filter((l) => l.i !== id),
          },
        })),

      setLayouts: (layouts) =>
        set((s) => ({
          ...s,
          layouts: JSON.parse(JSON.stringify(layouts)) as LayoutsByBreakpoint,
        })),

      resetToDefault: () =>
        set(() => ({
          version: 1,
          widgets: [...DEFAULT_WIDGETS],
          layouts: JSON.parse(
            JSON.stringify(DEFAULT_LAYOUTS),
          ) as LayoutsByBreakpoint,
        })),
    }),
    {
      name: LAYOUT_STORAGE_KEY,
      storage: createJSONStorage(() => localStorage),
      version: 1,
      merge: (persisted, current) => {
        const result = v.safeParse(StateSchema, persisted);
        if (!result.success) {
          logger.warn("layout rehydrate: schema mismatch; resetting", {
            issues: result.issues.map((i) => ({
              path: i.path?.map((p) => p.key),
              kind: i.kind,
            })),
          });
          return current;
        }
        const cleaned = cleanUnknowns(result.output.widgets);
        return {
          ...current,
          version: 1,
          widgets: cleaned,
          layouts: result.output.layouts as LayoutsByBreakpoint,
        };
      },
    },
  ),
);
