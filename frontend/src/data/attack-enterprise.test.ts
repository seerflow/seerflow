import { describe, it, expect } from "vitest";
import catalog from "./attack-enterprise.json";

describe("attack-enterprise catalog", () => {
  it("has 14 tactics", () => {
    expect(catalog.tactics).toHaveLength(14);
  });

  it("each tactic has id, shortname, name, and techniques array", () => {
    for (const tactic of catalog.tactics) {
      expect(tactic.id).toMatch(/^TA\d{4}$/);
      expect(tactic.shortname).toBeTruthy();
      expect(tactic.name).toBeTruthy();
      expect(Array.isArray(tactic.techniques)).toBe(true);
      expect(tactic.techniques.length).toBeGreaterThan(0);
    }
  });

  it("each technique has id and name", () => {
    for (const tactic of catalog.tactics) {
      for (const tech of tactic.techniques) {
        expect(tech.id).toMatch(/^T\d{4}$/);
        expect(tech.name).toBeTruthy();
      }
    }
  });

  it("tactic shortnames match backend TACTICS keys", () => {
    const expected = [
      "reconnaissance", "resource_development", "initial_access", "execution",
      "persistence", "privilege_escalation", "defense_evasion", "credential_access",
      "discovery", "lateral_movement", "collection", "exfiltration",
      "command_and_control", "impact",
    ];
    expect(catalog.tactics.map((t) => t.shortname)).toEqual(expected);
  });
});
