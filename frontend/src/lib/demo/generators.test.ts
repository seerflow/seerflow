import { describe, it, expect } from "vitest";
import {
  generateSeriesSamples,
  generateGraphData,
  generateEventBatch,
} from "./generators";

// --------------------------------------------------------------------------
// Determinism — same seed → same output
// --------------------------------------------------------------------------
describe("generateSeriesSamples", () => {
  it("returns the requested number of samples", () => {
    const samples = generateSeriesSamples({ count: 60 });
    expect(samples).toHaveLength(60);
  });

  it("returns deterministic output with same seed", () => {
    const a = generateSeriesSamples({ count: 10, seed: 42 });
    const b = generateSeriesSamples({ count: 10, seed: 42 });
    expect(a).toEqual(b);
  });

  it("returns different output with different seeds", () => {
    const a = generateSeriesSamples({ count: 10, seed: 1 });
    const b = generateSeriesSamples({ count: 10, seed: 2 });
    expect(a).not.toEqual(b);
  });

  it("each sample has correct shape", () => {
    const [s] = generateSeriesSamples({ count: 1 });
    expect(s).toHaveProperty("timestamp");
    expect(s).toHaveProperty("info");
    expect(s).toHaveProperty("warn");
    expect(s).toHaveProperty("crit");
    expect(typeof s.timestamp).toBe("number");
    expect(typeof s.info).toBe("number");
    expect(typeof s.warn).toBe("number");
    expect(typeof s.crit).toBe("number");
  });

  it("all values are non-negative", () => {
    const samples = generateSeriesSamples({ count: 100 });
    for (const s of samples) {
      expect(s.info).toBeGreaterThanOrEqual(0);
      expect(s.warn).toBeGreaterThanOrEqual(0);
      expect(s.crit).toBeGreaterThanOrEqual(0);
    }
  });

  it("timestamps are monotonically increasing", () => {
    const samples = generateSeriesSamples({ count: 50 });
    for (let i = 1; i < samples.length; i++) {
      expect(samples[i].timestamp).toBeGreaterThan(samples[i - 1].timestamp);
    }
  });

  it("default count is 900 (15min@1s)", () => {
    const samples = generateSeriesSamples({});
    expect(samples).toHaveLength(900);
  });

  it("startTime option shifts timestamps", () => {
    const t0 = 1_700_000_000;
    const samples = generateSeriesSamples({ count: 5, startTime: t0 });
    expect(samples[0].timestamp).toBeGreaterThanOrEqual(t0);
  });
});

// --------------------------------------------------------------------------
describe("generateGraphData", () => {
  it("returns nodes and edges arrays", () => {
    const { nodes, edges } = generateGraphData({ seed: 1 });
    expect(Array.isArray(nodes)).toBe(true);
    expect(Array.isArray(edges)).toBe(true);
  });

  it("is deterministic with same seed", () => {
    const a = generateGraphData({ seed: 7 });
    const b = generateGraphData({ seed: 7 });
    expect(a.nodes).toEqual(b.nodes);
    expect(a.edges).toEqual(b.edges);
  });

  it("different seeds produce different graphs", () => {
    const a = generateGraphData({ seed: 1 });
    const b = generateGraphData({ seed: 999 });
    expect(a.nodes).not.toEqual(b.nodes);
  });

  it("each node has required fields", () => {
    const { nodes } = generateGraphData({});
    for (const n of nodes) {
      expect(n).toHaveProperty("entity_uuid");
      expect(n).toHaveProperty("entity_type");
      expect(n).toHaveProperty("entity_value");
      expect(n).toHaveProperty("risk_score");
      expect(n).toHaveProperty("event_count");
      expect(n).toHaveProperty("alert_count");
      expect(n.risk_score).toBeGreaterThanOrEqual(0);
      expect(n.risk_score).toBeLessThanOrEqual(1);
    }
  });

  it("each edge has required fields", () => {
    const { edges } = generateGraphData({});
    for (const e of edges) {
      expect(e).toHaveProperty("source_uuid");
      expect(e).toHaveProperty("target_uuid");
      expect(e).toHaveProperty("relation_type");
      expect(e).toHaveProperty("severity");
    }
  });

  it("nodeCount option controls number of nodes", () => {
    const { nodes } = generateGraphData({ nodeCount: 5 });
    expect(nodes).toHaveLength(5);
  });

  it("all edge source/target UUIDs reference existing nodes", () => {
    const { nodes, edges } = generateGraphData({ nodeCount: 8 });
    const uuids = new Set(nodes.map((n) => n.entity_uuid));
    for (const e of edges) {
      expect(uuids).toContain(e.source_uuid);
      expect(uuids).toContain(e.target_uuid);
    }
  });
});

// --------------------------------------------------------------------------
describe("generateEventBatch", () => {
  it("returns requested number of events", () => {
    const events = generateEventBatch({ count: 18 });
    expect(events).toHaveLength(18);
  });

  it("is deterministic with same seed", () => {
    const a = generateEventBatch({ count: 5, seed: 3 });
    const b = generateEventBatch({ count: 5, seed: 3 });
    expect(a).toEqual(b);
  });

  it("each event has required fields", () => {
    const [ev] = generateEventBatch({ count: 1 });
    expect(ev).toHaveProperty("timestamp");
    expect(ev).toHaveProperty("level");
    expect(ev).toHaveProperty("source");
    expect(ev).toHaveProperty("host");
    expect(ev).toHaveProperty("logger");
    expect(ev).toHaveProperty("message");
  });

  it("levels are drawn from valid set", () => {
    const events = generateEventBatch({ count: 50 });
    const validLevels = new Set(["INFO", "WARN", "CRIT"]);
    for (const ev of events) {
      expect(validLevels).toContain(ev.level);
    }
  });

  it("default count is 18 (one screen of events)", () => {
    const events = generateEventBatch({});
    expect(events).toHaveLength(18);
  });
});
