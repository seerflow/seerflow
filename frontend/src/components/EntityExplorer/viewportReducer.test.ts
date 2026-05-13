import { describe, it, expect } from "vitest";
import {
  INITIAL_VIEW,
  MAX_SCALE,
  MIN_SCALE,
  clamp,
  viewportReducer,
} from "./viewportReducer";

describe("viewportReducer", () => {
  describe("clamp", () => {
    it("returns lo when n < lo", () => expect(clamp(-1, 0, 10)).toBe(0));
    it("returns hi when n > hi", () => expect(clamp(99, 0, 10)).toBe(10));
    it("returns n when in range", () => expect(clamp(5, 0, 10)).toBe(5));
  });

  describe("zoomBy", () => {
    it("multiplies scale", () => {
      const next = viewportReducer(INITIAL_VIEW, { kind: "zoomBy", factor: 1.5 });
      expect(next.scale).toBe(1.5);
    });
    it("clamps to MAX_SCALE", () => {
      const next = viewportReducer(INITIAL_VIEW, { kind: "zoomBy", factor: 100 });
      expect(next.scale).toBe(MAX_SCALE);
    });
    it("clamps to MIN_SCALE", () => {
      const next = viewportReducer(INITIAL_VIEW, { kind: "zoomBy", factor: 0.001 });
      expect(next.scale).toBe(MIN_SCALE);
    });
    it("does not change tx/ty", () => {
      const start = { scale: 1, tx: 50, ty: -20 };
      const next = viewportReducer(start, { kind: "zoomBy", factor: 1.2 });
      expect(next.tx).toBe(50);
      expect(next.ty).toBe(-20);
    });
  });

  describe("wheelAt (cursor-anchored zoom)", () => {
    it("keeps the cursor-anchored graph point fixed on screen", () => {
      const start: typeof INITIAL_VIEW = { scale: 1, tx: 0, ty: 0 };
      const next = viewportReducer(start, {
        kind: "wheelAt",
        deltaY: -100,
        ox: 100,
        oy: 100,
      });
      const graphX = (100 - next.tx) / next.scale;
      const graphY = (100 - next.ty) / next.scale;
      expect(graphX).toBeCloseTo(100, 5);
      expect(graphY).toBeCloseTo(100, 5);
      expect(next.scale).toBeGreaterThan(1);
    });

    it("clamps at MAX_SCALE without nudging tx/ty when already at limit", () => {
      const start: typeof INITIAL_VIEW = { scale: MAX_SCALE, tx: 10, ty: 20 };
      const next = viewportReducer(start, {
        kind: "wheelAt",
        deltaY: -1000,
        ox: 50,
        oy: 50,
      });
      expect(next.scale).toBe(MAX_SCALE);
      expect(next.tx).toBe(10);
      expect(next.ty).toBe(20);
    });

    it("clamps at MIN_SCALE without nudging tx/ty when already at limit", () => {
      const start: typeof INITIAL_VIEW = { scale: MIN_SCALE, tx: 10, ty: 20 };
      const next = viewportReducer(start, {
        kind: "wheelAt",
        deltaY: 1000,
        ox: 50,
        oy: 50,
      });
      expect(next.scale).toBe(MIN_SCALE);
      expect(next.tx).toBe(10);
      expect(next.ty).toBe(20);
    });
  });

  describe("panBy", () => {
    it("adds dx/dy to tx/ty", () => {
      const start: typeof INITIAL_VIEW = { scale: 2, tx: 10, ty: 20 };
      const next = viewportReducer(start, { kind: "panBy", dx: 5, dy: -3 });
      expect(next).toEqual({ scale: 2, tx: 15, ty: 17 });
    });
  });

  describe("reset", () => {
    it("returns INITIAL_VIEW", () => {
      const start: typeof INITIAL_VIEW = { scale: 2.5, tx: 100, ty: -50 };
      const next = viewportReducer(start, { kind: "reset" });
      expect(next).toEqual(INITIAL_VIEW);
    });
  });
});
