/**
 * S-328 — live-data selectors with demo fallback.
 *
 * Pure functions that read whatever the store/endpoint exposes and degrade to
 * the existing demo constants when the live value is absent. Keeps screens
 * thin and the fallback contract independently testable (AC1–AC5).
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import type { EntityEvent, RiskBucket } from "@/lib/types";

import {
  DEMO_ACTIVE_ENTITIES,
  DEMO_MEAN_LATENCY_MS,
  DEMO_UPTIME_LABEL,
  DEMO_EVENTS_PER_SEC,
  selectActiveEntities,
  selectMeanLatencyMs,
  selectSidebarHealth,
  selectFocalEntityStats,
  fetchAlertExplanation,
} from "@/lib/liveStats";

// ── Test fixtures ───────────────────────────────────────────────────────────

function ev(severity_id: number, id = `e${severity_id}`): EntityEvent {
  return {
    event_id: id,
    timestamp_ns: 0n,
    source_type: "test",
    severity_id,
    message: "m",
    related_ips: [],
    related_users: [],
    related_hosts: [],
    related_domains: [],
  };
}

function bucket(alert_count: number): RiskBucket {
  return { bucket_start_ns: "0", points: 0, alert_count, top_rule_name: "" };
}

// ── AC1: Overview KPI selectors ───────────────────────────────────────────────

describe("selectActiveEntities", () => {
  it("returns the live value when > 0", () => {
    expect(selectActiveEntities(4_812)).toBe(4_812);
  });
  it("falls back to the demo constant when 0", () => {
    expect(selectActiveEntities(0)).toBe(DEMO_ACTIVE_ENTITIES);
  });
});

describe("selectMeanLatencyMs", () => {
  it("returns the live value when > 0", () => {
    expect(selectMeanLatencyMs(54)).toBe(54);
  });
  it("falls back to the demo constant when 0", () => {
    expect(selectMeanLatencyMs(0)).toBe(DEMO_MEAN_LATENCY_MS);
  });
});

// ── AC2: Sidebar health selector ──────────────────────────────────────────────

describe("selectSidebarHealth", () => {
  it("returns live values when both present", () => {
    expect(
      selectSidebarHealth({ uptimeLabel: "9d 2h", evPerSec: 9_001 }),
    ).toEqual({ uptimeLabel: "9d 2h", evPerSec: 9_001 });
  });
  it("falls back to demo uptime when label is the unknown placeholder", () => {
    expect(
      selectSidebarHealth({ uptimeLabel: "—", evPerSec: 9_001 }),
    ).toEqual({ uptimeLabel: DEMO_UPTIME_LABEL, evPerSec: 9_001 });
  });
  it("falls back to demo ev/s when evPerSec is 0", () => {
    expect(
      selectSidebarHealth({ uptimeLabel: "9d 2h", evPerSec: 0 }),
    ).toEqual({ uptimeLabel: "9d 2h", evPerSec: DEMO_EVENTS_PER_SEC });
  });
  it("falls back fully when the store is at its defaults", () => {
    expect(
      selectSidebarHealth({ uptimeLabel: "—", evPerSec: 0 }),
    ).toEqual({ uptimeLabel: DEMO_UPTIME_LABEL, evPerSec: DEMO_EVENTS_PER_SEC });
  });
});

// ── AC3: Focal-entity stats selector ──────────────────────────────────────────

describe("selectFocalEntityStats", () => {
  it("prefers `total` for eventCount, sums risk-bucket alert counts, normalises risk", () => {
    const events = [ev(2), ev(5), ev(3)];
    const stats = selectFocalEntityStats(events, 1_204, [bucket(2), bucket(5)]);
    expect(stats.eventCount).toBe(1_204);
    expect(stats.alertCount).toBe(7);
    // max severity 5 of 6 → 0.8333…
    expect(stats.risk).toBeCloseTo(5 / 6, 5);
  });

  it("uses events.length when total is 0", () => {
    const events = [ev(1), ev(4)];
    const stats = selectFocalEntityStats(events, 0, []);
    expect(stats.eventCount).toBe(2);
    expect(stats.alertCount).toBe(0);
    expect(stats.risk).toBeCloseTo(4 / 6, 5);
  });

  it("returns all-zero for empty inputs", () => {
    expect(selectFocalEntityStats([], 0, [])).toEqual({
      risk: 0,
      eventCount: 0,
      alertCount: 0,
    });
  });

  it("clamps risk to at most 1 even for an out-of-range severity_id", () => {
    const stats = selectFocalEntityStats([ev(12)], 0, []);
    expect(stats.risk).toBeLessThanOrEqual(1);
    expect(stats.risk).toBe(1);
  });
});

// ── AC4: LLM-explain endpoint helper ──────────────────────────────────────────

describe("fetchAlertExplanation", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns the narrative when the endpoint resolves", async () => {
    const { api } = await import("@/lib/api");
    vi.spyOn(api, "get").mockResolvedValueOnce({ narrative: "LLM says hi" });
    await expect(fetchAlertExplanation("alert-1")).resolves.toBe("LLM says hi");
  });

  it("returns null (no throw, no console error) when the endpoint rejects", async () => {
    const { api } = await import("@/lib/api");
    vi.spyOn(api, "get").mockRejectedValueOnce(new Error("404 not found"));
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    await expect(fetchAlertExplanation("alert-1")).resolves.toBeNull();
    expect(errSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("returns null when the payload is malformed (no narrative string)", async () => {
    const { api } = await import("@/lib/api");
    vi.spyOn(api, "get").mockResolvedValueOnce({ nope: 1 });
    await expect(fetchAlertExplanation("alert-1")).resolves.toBeNull();
  });

  it("passes the abort signal through to api.get", async () => {
    const { api } = await import("@/lib/api");
    const spy = vi
      .spyOn(api, "get")
      .mockResolvedValueOnce({ narrative: "x" });
    const ctrl = new AbortController();
    await fetchAlertExplanation("alert-9", ctrl.signal);
    expect(spy).toHaveBeenCalledWith(
      "/api/v1/alerts/alert-9/explain",
      expect.objectContaining({ signal: ctrl.signal }),
    );
  });
});
