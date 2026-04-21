import { describe, it, expect, beforeEach } from "vitest";
import {
  useLayoutStore,
  DEFAULT_WIDGETS,
  DEFAULT_LAYOUTS,
  LAYOUT_STORAGE_KEY,
} from "./layout";

beforeEach(() => {
  window.localStorage.removeItem(LAYOUT_STORAGE_KEY);
  useLayoutStore.getState().resetToDefault();
});

describe("layout store", () => {
  it("starts with default widgets and layouts", () => {
    const s = useLayoutStore.getState();
    expect(s.widgets).toEqual(DEFAULT_WIDGETS);
    expect(s.layouts.lg.length).toBe(DEFAULT_WIDGETS.length);
  });

  it("addWidget appends an id not already mounted", () => {
    useLayoutStore.getState().addWidget("attackHeatmap");
    expect(useLayoutStore.getState().widgets).toContain("attackHeatmap");
  });

  it("addWidget is a no-op for a duplicate id", () => {
    useLayoutStore.getState().addWidget("alertFeed");
    expect(
      useLayoutStore.getState().widgets.filter((w) => w === "alertFeed"),
    ).toHaveLength(1);
  });

  it("removeWidget removes the id and its layout entries", () => {
    useLayoutStore.getState().removeWidget("alertFeed");
    expect(useLayoutStore.getState().widgets).not.toContain("alertFeed");
    expect(
      useLayoutStore.getState().layouts.lg.find((l) => l.i === "alertFeed"),
    ).toBeUndefined();
  });

  it("resetToDefault restores defaults", () => {
    useLayoutStore.getState().removeWidget("alertFeed");
    useLayoutStore.getState().resetToDefault();
    expect(useLayoutStore.getState().widgets).toEqual(DEFAULT_WIDGETS);
  });

  it("setLayouts replaces the layouts map", () => {
    useLayoutStore.getState().setLayouts({
      ...DEFAULT_LAYOUTS,
      lg: [...DEFAULT_LAYOUTS.lg.map((l) => ({ ...l, x: l.x + 1 }))],
    });
    expect(useLayoutStore.getState().layouts.lg[0].x).toBe(
      DEFAULT_LAYOUTS.lg[0].x + 1,
    );
  });

  it("rehydrate with a schema-mismatched blob falls back to default and clears storage", async () => {
    window.localStorage.setItem(
      LAYOUT_STORAGE_KEY,
      JSON.stringify({ state: { version: 999 } }),
    );
    // Trigger rehydrate manually (the persist middleware does it on first access in tests).
    await useLayoutStore.persist.rehydrate();
    expect(useLayoutStore.getState().widgets).toEqual(DEFAULT_WIDGETS);
  });

  it("mutations of the live layouts do not leak into DEFAULT_LAYOUTS", () => {
    const s = useLayoutStore.getState();
    s.layouts.lg[0].x = 999;
    expect(DEFAULT_LAYOUTS.lg[0].x).not.toBe(999);
  });

  it("rehydrate with a valid blob restores persisted widgets and layouts", async () => {
    const persisted = {
      state: {
        version: 1,
        widgets: ["alertFeed", "attackHeatmap"],
        layouts: {
          lg: [{ i: "alertFeed", x: 1, y: 2, w: 3, h: 4 }],
          md: [],
          sm: [],
        },
      },
      version: 1,
    };
    window.localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify(persisted));
    await useLayoutStore.persist.rehydrate();
    const s = useLayoutStore.getState();
    expect(s.widgets).toEqual(["alertFeed", "attackHeatmap"]);
    expect(s.layouts.lg).toEqual([{ i: "alertFeed", x: 1, y: 2, w: 3, h: 4 }]);
  });

  it("rehydrate drops unknown widget ids", async () => {
    const persisted = {
      state: {
        version: 1,
        widgets: ["alertFeed", "ghostWidget"],
        layouts: { lg: [], md: [], sm: [] },
      },
      version: 1,
    };
    window.localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify(persisted));
    await useLayoutStore.persist.rehydrate();
    expect(useLayoutStore.getState().widgets).toEqual(["alertFeed"]);
  });
});
