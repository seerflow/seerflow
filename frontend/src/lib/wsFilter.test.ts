import { beforeEach, describe, expect, it } from "vitest";
import { createFilterSlot, _resetForTests } from "./wsFilter";

describe("wsFilter (via createFilterSlot)", () => {
  beforeEach(() => _resetForTests());

  it("returns empty filter when no intents set", () => {
    const alerts = createFilterSlot("alerts");
    const r = alerts.set({});
    expect(r).toEqual({ type: "filter" });
  });

  it("alerts intent only — alert_types + min_severity present", () => {
    const alerts = createFilterSlot("alerts");
    const r = alerts.set({ alert_types: ["sigma"], min_severity: 13 });
    expect(r).toEqual({ type: "filter", alert_types: ["sigma"], min_severity: 13 });
  });

  it("events intent only — sources + template_ids + min_severity present", () => {
    const events = createFilterSlot("events");
    const r = events.set({ sources: ["auth"], template_ids: [17], min_severity: 4 });
    expect(r).toEqual({ type: "filter", sources: ["auth"], template_ids: [17], min_severity: 4 });
  });

  it("merges union of arrays across both intents", () => {
    const alerts = createFilterSlot("alerts");
    const events = createFilterSlot("events");
    alerts.set({ sources: ["syslog"] });
    const r = events.set({ sources: ["auth"] });
    expect(r.sources?.sort()).toEqual(["auth", "syslog"]);
  });

  it("uses MIN of min_severity across intents (most permissive wins)", () => {
    const alerts = createFilterSlot("alerts");
    const events = createFilterSlot("events");
    alerts.set({ min_severity: 13 });
    const r = events.set({ min_severity: 4 });
    expect(r.min_severity).toBe(4);
  });

  it("omits empty arrays so server reads as 'match all'", () => {
    const alerts = createFilterSlot("alerts");
    const events = createFilterSlot("events");
    alerts.set({ sources: [] });
    const r = events.set({ sources: [] });
    expect(r.sources).toBeUndefined();
  });

  it("set() replaces a widget's prior intent (not merges with itself)", () => {
    const events = createFilterSlot("events");
    events.set({ sources: ["auth", "syslog"] });
    const r = events.set({ sources: ["dns"] });
    expect(r.sources).toEqual(["dns"]);
  });

  it("clear() removes a widget's intent and re-merges", () => {
    const alerts = createFilterSlot("alerts");
    const events = createFilterSlot("events");
    alerts.set({ alert_types: ["sigma"], min_severity: 13 });
    events.set({ sources: ["auth"], min_severity: 4 });
    const r = events.clear();
    expect(r).toEqual({ type: "filter", alert_types: ["sigma"], min_severity: 13 });
  });
});

describe("createFilterSlot", () => {
  beforeEach(() => _resetForTests());

  it("returns a set/clear closure scoped to the widget", () => {
    const slot = createFilterSlot("alerts");
    const merged = slot.set({ sources: ["syslog"] });
    expect(merged.sources).toEqual(["syslog"]);
    slot.clear();
  });

  it("throws when a slot is issued twice for the same widget", () => {
    createFilterSlot("alerts");
    expect(() => createFilterSlot("alerts")).toThrow(/already issued/);
  });

  it("keeps alerts + events intents isolated", () => {
    const a = createFilterSlot("alerts");
    const e = createFilterSlot("events");
    a.set({ sources: ["s1"] });
    const merged = e.set({ sources: ["s2"] });
    expect(new Set(merged.sources!)).toEqual(new Set(["s1", "s2"]));
  });

  it("clear() resets the slot's intent to empty and returns merged", () => {
    const a = createFilterSlot("alerts");
    const e = createFilterSlot("events");
    a.set({ sources: ["s1"] });
    e.set({ sources: ["s2"] });
    const cleared = a.clear();
    expect(cleared.sources).toEqual(["s2"]);
  });

  it("_resetForTests clears both intents and the issued set", () => {
    createFilterSlot("alerts");
    _resetForTests();
    expect(() => createFilterSlot("alerts")).not.toThrow();
  });
});

describe("wsFilter public surface", () => {
  it("does not export setIntent or clearIntent", async () => {
    const mod = await import("./wsFilter");
    expect((mod as Record<string, unknown>).setIntent).toBeUndefined();
    expect((mod as Record<string, unknown>).clearIntent).toBeUndefined();
  });
});
