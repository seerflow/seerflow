import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import {
  useLayoutStore,
  DEFAULT_WIDGETS,
  DEFAULT_LAYOUTS,
  LAYOUT_STORAGE_KEY,
} from "./layout";
import { logger } from "@/lib/logger";

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

  it("removeWidget removes the id and strips its layout entries from every breakpoint", () => {
    useLayoutStore.getState().removeWidget("alertFeed");
    const state = useLayoutStore.getState();
    expect(state.widgets).not.toContain("alertFeed");
    expect(state.layouts.lg.find((l) => l.i === "alertFeed")).toBeUndefined();
    expect(state.layouts.md.find((l) => l.i === "alertFeed")).toBeUndefined();
    expect(state.layouts.sm.find((l) => l.i === "alertFeed")).toBeUndefined();
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

  it("setLayouts does not alias the caller's array (deep-copies on commit)", () => {
    const lg = DEFAULT_LAYOUTS.lg.map((l) => ({ ...l }));
    useLayoutStore.getState().setLayouts({ ...DEFAULT_LAYOUTS, lg });
    lg[0].x = 999;
    expect(useLayoutStore.getState().layouts.lg[0].x).not.toBe(999);
  });

  it("resetToDefault rebuilds layouts from an unmutated DEFAULT_LAYOUTS", () => {
    const before = DEFAULT_LAYOUTS.lg[0].x;
    const live = useLayoutStore.getState().layouts;
    live.lg[0].x = 999;
    useLayoutStore.getState().resetToDefault();
    expect(DEFAULT_LAYOUTS.lg[0].x).toBe(before);
    expect(useLayoutStore.getState().layouts.lg[0].x).toBe(before);
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

  describe("rehydrate logger.warn assertions", () => {
    let warnSpy: ReturnType<typeof vi.spyOn>;
    beforeEach(() => {
      warnSpy = vi.spyOn(logger, "warn").mockImplementation(() => undefined);
    });
    afterEach(() => {
      warnSpy.mockRestore();
    });

    it("emits a single 'schema mismatch' warn on a malformed blob", async () => {
      window.localStorage.setItem(
        LAYOUT_STORAGE_KEY,
        JSON.stringify({ state: { version: 999 } }),
      );
      await useLayoutStore.persist.rehydrate();
      const matching = warnSpy.mock.calls.filter((c) =>
        String(c[0]).includes("layout rehydrate: schema mismatch"),
      );
      expect(matching).toHaveLength(1);
    });

    it("emits a single 'dropping unknown widget ids' warn with the dropped payload", async () => {
      const persisted = {
        state: {
          version: 1,
          widgets: ["alertFeed", "ghostWidget", "phantomWidget"],
          layouts: { lg: [], md: [], sm: [] },
        },
        version: 1,
      };
      window.localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify(persisted));
      await useLayoutStore.persist.rehydrate();
      const matching = warnSpy.mock.calls.filter((c) =>
        String(c[0]).includes("dropping unknown widget ids"),
      );
      expect(matching).toHaveLength(1);
      expect(matching[0][1]).toEqual({
        dropped: ["ghostWidget", "phantomWidget"],
      });
    });
  });
});
