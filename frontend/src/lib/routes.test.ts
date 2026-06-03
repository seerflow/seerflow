import { describe, it, expect } from "vitest";
import {
  parseHash,
  serializeHash,
  ROUTE_REGISTRY,
  type RouteMatch,
} from "./routes";

const VALID_UUID = "11111111-2222-3333-4444-555555555555";

describe("parseHash — new hash format", () => {
  it("empty hash → overview", () => {
    expect(parseHash("")).toEqual({ route: "overview" });
  });

  it("bare # → overview", () => {
    expect(parseHash("#")).toEqual({ route: "overview" });
  });

  it("#/overview", () => {
    expect(parseHash("#/overview")).toEqual({ route: "overview" });
  });

  it("#/alerts (list)", () => {
    expect(parseHash("#/alerts")).toEqual({ route: "alerts" });
  });

  it("#/alerts/:id", () => {
    expect(parseHash("#/alerts/abc-123")).toEqual({ route: "alerts", id: "abc-123" });
  });

  it("#/events", () => {
    expect(parseHash("#/events")).toEqual({ route: "events" });
  });

  it("#/entities (list)", () => {
    expect(parseHash("#/entities")).toEqual({ route: "entities" });
  });

  it("#/entities/:uuid", () => {
    expect(parseHash(`#/entities/${VALID_UUID}`)).toEqual({
      route: "entities",
      uuid: VALID_UUID,
    });
  });

  it("#/attack", () => {
    expect(parseHash("#/attack")).toEqual({ route: "attack" });
  });

  it("#/sigma (list)", () => {
    expect(parseHash("#/sigma")).toEqual({ route: "sigma" });
  });

  it("#/sigma/:id", () => {
    expect(parseHash("#/sigma/win_susp_download")).toEqual({
      route: "sigma",
      id: "win_susp_download",
    });
  });

  it("#/hunt", () => {
    expect(parseHash("#/hunt")).toEqual({ route: "hunt" });
  });

  it("#/receivers", () => {
    expect(parseHash("#/receivers")).toEqual({ route: "receivers" });
  });

  it("#/models", () => {
    expect(parseHash("#/models")).toEqual({ route: "models" });
  });

  it("#/settings", () => {
    expect(parseHash("#/settings")).toEqual({ route: "settings" });
  });
});

describe("parseHash — legacy hash backward compat", () => {
  it("legacy #entity=<uuid> → entities route with uuid", () => {
    expect(
      parseHash(`#entity=${VALID_UUID}&range=24h`),
    ).toEqual({ route: "entities", uuid: VALID_UUID });
  });

  it("legacy #entity=<uuid> without range param", () => {
    expect(parseHash(`#entity=${VALID_UUID}`)).toEqual({
      route: "entities",
      uuid: VALID_UUID,
    });
  });

  it("legacy #coverage → attack route", () => {
    expect(parseHash("#coverage")).toEqual({ route: "attack" });
  });

  it("legacy #sigma-rules → sigma route", () => {
    expect(parseHash("#sigma-rules")).toEqual({ route: "sigma" });
  });
});

describe("serializeHash", () => {
  it("overview → #/overview", () => {
    expect(serializeHash({ route: "overview" })).toBe("#/overview");
  });

  it("alerts list → #/alerts", () => {
    expect(serializeHash({ route: "alerts" })).toBe("#/alerts");
  });

  it("alerts detail → #/alerts/abc-123", () => {
    expect(serializeHash({ route: "alerts", id: "abc-123" })).toBe(
      "#/alerts/abc-123",
    );
  });

  it("entities list → #/entities", () => {
    expect(serializeHash({ route: "entities" })).toBe("#/entities");
  });

  it("entities with uuid → #/entities/<uuid>", () => {
    expect(serializeHash({ route: "entities", uuid: VALID_UUID })).toBe(
      `#/entities/${VALID_UUID}`,
    );
  });

  it("sigma list → #/sigma", () => {
    expect(serializeHash({ route: "sigma" })).toBe("#/sigma");
  });

  it("sigma detail → #/sigma/win_susp_download", () => {
    expect(serializeHash({ route: "sigma", id: "win_susp_download" })).toBe(
      "#/sigma/win_susp_download",
    );
  });

  it("hunt → #/hunt", () => {
    expect(serializeHash({ route: "hunt" })).toBe("#/hunt");
  });
});

describe("ROUTE_REGISTRY", () => {
  const routeNames = ROUTE_REGISTRY.map((r) => r.route);

  it("contains all 13 routes", () => {
    const expected = [
      "overview",
      "alerts",
      "events",
      "entities",
      "attack",
      "hunt",
      "sigma",
      "receivers",
      "models",
      "settings",
    ];
    for (const name of expected) {
      expect(routeNames).toContain(name);
    }
  });

  it("each entry has label, group, and iconPath", () => {
    for (const entry of ROUTE_REGISTRY) {
      expect(entry.label).toBeTruthy();
      expect(entry.group).toMatch(/^(Monitor|Investigate|Configure)$/);
      expect(entry.iconPath).toBeTruthy();
    }
  });

  it("groups are Monitor, Investigate, Configure", () => {
    const groups = new Set(ROUTE_REGISTRY.map((r) => r.group));
    expect(groups.has("Monitor")).toBe(true);
    expect(groups.has("Investigate")).toBe(true);
    expect(groups.has("Configure")).toBe(true);
  });

  it("Monitor group has Overview, Alerts, Events", () => {
    const monitor = ROUTE_REGISTRY.filter((r) => r.group === "Monitor").map(
      (r) => r.route,
    );
    expect(monitor).toContain("overview");
    expect(monitor).toContain("alerts");
    expect(monitor).toContain("events");
  });

  it("Investigate group has entities, attack, hunt", () => {
    const inv = ROUTE_REGISTRY.filter((r) => r.group === "Investigate").map(
      (r) => r.route,
    );
    expect(inv).toContain("entities");
    expect(inv).toContain("attack");
    expect(inv).toContain("hunt");
  });

  it("Configure group has sigma, receivers, models, settings", () => {
    const cfg = ROUTE_REGISTRY.filter((r) => r.group === "Configure").map(
      (r) => r.route,
    );
    expect(cfg).toContain("sigma");
    expect(cfg).toContain("receivers");
    expect(cfg).toContain("models");
    expect(cfg).toContain("settings");
  });
});

describe("RouteMatch type exhaustiveness", () => {
  it("route property is always a string", () => {
    const m: RouteMatch = parseHash("#/overview");
    expect(typeof m.route).toBe("string");
  });
});
