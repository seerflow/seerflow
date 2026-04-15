import { beforeEach, describe, expect, it } from "vitest";
import { setIntent, clearIntent, _resetForTests } from "./wsFilter";

describe("wsFilter", () => {
  beforeEach(() => _resetForTests());

  it("returns empty filter when no intents set", () => {
    const r = setIntent("alerts", {});
    expect(r).toEqual({ type: "filter" });
  });

  it("alerts intent only — alert_types + min_severity present", () => {
    const r = setIntent("alerts", { alert_types: ["sigma"], min_severity: 13 });
    expect(r).toEqual({ type: "filter", alert_types: ["sigma"], min_severity: 13 });
  });

  it("events intent only — sources + template_ids + min_severity present", () => {
    const r = setIntent("events", { sources: ["auth"], template_ids: [17], min_severity: 4 });
    expect(r).toEqual({ type: "filter", sources: ["auth"], template_ids: [17], min_severity: 4 });
  });

  it("merges union of arrays across both intents", () => {
    setIntent("alerts", { sources: ["syslog"] });
    const r = setIntent("events", { sources: ["auth"] });
    expect(r.sources?.sort()).toEqual(["auth", "syslog"]);
  });

  it("uses MIN of min_severity across intents (most permissive wins)", () => {
    setIntent("alerts", { min_severity: 13 });
    const r = setIntent("events", { min_severity: 4 });
    expect(r.min_severity).toBe(4);
  });

  it("omits empty arrays so server reads as 'match all'", () => {
    setIntent("alerts", { sources: [] });
    const r = setIntent("events", { sources: [] });
    expect(r.sources).toBeUndefined();
  });

  it("setIntent replaces a widget's prior intent (not merges with itself)", () => {
    setIntent("events", { sources: ["auth", "syslog"] });
    const r = setIntent("events", { sources: ["dns"] });
    expect(r.sources).toEqual(["dns"]);
  });

  it("clearIntent removes a widget's intent and re-merges", () => {
    setIntent("alerts", { alert_types: ["sigma"], min_severity: 13 });
    setIntent("events", { sources: ["auth"], min_severity: 4 });
    const r = clearIntent("events");
    expect(r).toEqual({ type: "filter", alert_types: ["sigma"], min_severity: 13 });
  });
});
