import { describe, it, expect, beforeEach } from "vitest";
import { useDrilldownStore } from "./drilldown";

describe("useDrilldownStore", () => {
  beforeEach(() => {
    useDrilldownStore.getState().close();
  });

  it("starts with no open cell", () => {
    expect(useDrilldownStore.getState().openCell).toBeNull();
  });

  it("open() sets the open cell", () => {
    useDrilldownStore.getState().open("execution", "T1053");
    expect(useDrilldownStore.getState().openCell).toEqual({
      tactic: "execution",
      technique: "T1053",
    });
  });

  it("close() clears the open cell", () => {
    useDrilldownStore.getState().open("execution", "T1053");
    useDrilldownStore.getState().close();
    expect(useDrilldownStore.getState().openCell).toBeNull();
  });

  it("open() with the same cell is a no-op (reference identity preserved)", () => {
    useDrilldownStore.getState().open("execution", "T1053");
    const before = useDrilldownStore.getState().openCell;
    useDrilldownStore.getState().open("execution", "T1053");
    const after = useDrilldownStore.getState().openCell;
    expect(after).toBe(before);
  });

  it("open() with a different cell switches", () => {
    useDrilldownStore.getState().open("execution", "T1053");
    useDrilldownStore.getState().open("persistence", "T1547");
    expect(useDrilldownStore.getState().openCell).toEqual({
      tactic: "persistence",
      technique: "T1547",
    });
  });
});
