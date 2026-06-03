import { describe, it, expect } from "vitest";
import type { Alert } from "@/lib/types";
import {
  KPI,
  deriveOwner,
  deriveStatus,
  entityChips,
  compactUpdated,
  tabCounts,
  type AlertStatus,
} from "./alertDemo";

function mkAlert(over: Partial<Alert> = {}): Alert {
  return {
    alert_id: "kc-94-1afe2b",
    timestamp_ns: 1_000_000_000n,
    alert_type: "correlation",
    rule_name: "kill_chain",
    severity: 5,
    risk_score: 0.94,
    entity_uuid: null,
    entity_type: "user",
    entity_value: "root@10.0.1.42",
    message: "preview",
    mitre_tactics: ["TA0006"],
    mitre_techniques: [],
    dedup_count: 47,
    source_type: "syslog",
    feedback: "",
    ...over,
  };
}

describe("alertDemo", () => {
  it("KPI constants match the mockup", () => {
    expect(KPI.mttd).toBe("38s");
    expect(KPI.mttr).toBe("14m");
    expect(KPI.fpRate).toBe("3.2%");
  });

  describe("deriveOwner", () => {
    it("is deterministic for the same id", () => {
      expect(deriveOwner("abc")).toBe(deriveOwner("abc"));
    });

    it("returns either a 2-char initials string or null", () => {
      const allowed = new Set(["jt", "mr", "ek", null]);
      for (const id of ["a", "kc-94-1afe2b", "sig-77-c0142a", "gph-31", "anm-04-d83c11"]) {
        expect(allowed.has(deriveOwner(id))).toBe(true);
      }
    });

    it("covers both the assigned and unassigned branches across ids", () => {
      const ids = Array.from({ length: 40 }, (_, i) => `alert-${i}`);
      const owners = ids.map(deriveOwner);
      expect(owners.some((o) => o === null)).toBe(true);
      expect(owners.some((o) => o !== null)).toBe(true);
    });
  });

  describe("deriveStatus", () => {
    it("is deterministic for the same alert id", () => {
      const a = mkAlert();
      expect(deriveStatus(a)).toBe(deriveStatus(a));
    });

    it("returns a known workflow status", () => {
      const known = new Set<AlertStatus>(["open", "triaging", "resolved", "suppressed"]);
      for (let i = 0; i < 40; i++) {
        expect(known.has(deriveStatus(mkAlert({ alert_id: `x-${i}`, severity: i % 7 })))).toBe(true);
      }
    });

    it("skews critical alerts toward open/triaging", () => {
      const crit = Array.from({ length: 30 }, (_, i) =>
        deriveStatus(mkAlert({ alert_id: `c-${i}`, severity: 6 })),
      );
      const active = crit.filter((s) => s === "open" || s === "triaging").length;
      expect(active).toBeGreaterThan(crit.length / 2);
    });
  });

  describe("entityChips", () => {
    it("maps a single entity to one chip", () => {
      const chips = entityChips(mkAlert());
      expect(chips).toEqual([{ kind: "user", value: "root@10.0.1.42" }]);
    });

    it("returns an empty list when no entity is present", () => {
      expect(entityChips(mkAlert({ entity_type: null, entity_value: null }))).toEqual([]);
    });

    it("falls back to host kind when only a value is present", () => {
      const chips = entityChips(mkAlert({ entity_type: null, entity_value: "web-04" }));
      expect(chips).toEqual([{ kind: "host", value: "web-04" }]);
    });
  });

  describe("compactUpdated", () => {
    const now = 100n * 60n * 1_000_000_000n; // 100 minutes in ns

    it('renders seconds without the word "ago"', () => {
      expect(compactUpdated(now - 12n * 1_000_000_000n, now)).toBe("12s");
    });

    it("renders minutes", () => {
      expect(compactUpdated(now - 2n * 60n * 1_000_000_000n, now)).toBe("2m");
    });

    it("renders hours", () => {
      expect(compactUpdated(now - 3n * 60n * 60n * 1_000_000_000n, now)).toBe("3h");
    });

    it("renders now for sub-second deltas", () => {
      expect(compactUpdated(now, now)).toBe("now");
    });
  });

  describe("tabCounts", () => {
    it("partitions the loaded set across the four workflow buckets", () => {
      const alerts = Array.from({ length: 12 }, (_, i) =>
        mkAlert({ alert_id: `t-${i}`, severity: i % 7 }),
      );
      const counts = tabCounts(alerts);
      expect(counts.open + counts.triaging + counts.resolved + counts.suppressed).toBe(
        alerts.length,
      );
    });

    it("all equals the loaded length (sum of the four buckets)", () => {
      const alerts = [mkAlert({ alert_id: "a" }), mkAlert({ alert_id: "b" })];
      const counts = tabCounts(alerts);
      expect(counts.all).toBe(alerts.length);
      expect(counts.suppressed).toBeGreaterThanOrEqual(0);
    });

    it("handles an empty set", () => {
      const counts = tabCounts([]);
      expect(counts.open).toBe(0);
      expect(counts.all).toBeGreaterThanOrEqual(0);
    });
  });
});
