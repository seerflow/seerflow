import { describe, it, expect } from "vitest";
import { applyEventQuery, countSeverities } from "./eventQuery";
import type { LiveEvent } from "@/lib/types";

function ev(over: Partial<LiveEvent> = {}): LiveEvent {
  return {
    event_id: "e1",
    timestamp_ns: 1n,
    observed_ns: 1n,
    severity_id: 2,
    severity_text: "INFO",
    source_type: "syslog",
    message: "hello world",
    template_id: 1,
    entity_refs: [],
    entity_summary: {},
    ...over,
  };
}

const events: LiveEvent[] = [
  ev({ event_id: "a", severity_id: 6, severity_text: "FATAL", source_type: "syslog", message: "disk failure on host01" }),
  ev({ event_id: "b", severity_id: 4, severity_text: "ERROR", source_type: "kafka", message: "auth denied for bob" }),
  ev({ event_id: "c", severity_id: 2, severity_text: "INFO", source_type: "syslog", message: "user login ok" }),
  ev({ event_id: "d", severity_id: 3, severity_text: "WARNING", source_type: "file", message: "slow query detected" }),
];

describe("applyEventQuery", () => {
  it("returns all events for an empty query (valid)", () => {
    const r = applyEventQuery(events, "");
    expect(r.matched).toHaveLength(events.length);
    expect(r.valid).toBe(true);
    expect(r.mode).toBe("all");
  });

  it("returns all events for a whitespace-only query", () => {
    const r = applyEventQuery(events, "   ");
    expect(r.matched).toHaveLength(events.length);
    expect(r.valid).toBe(true);
  });

  it("does not mutate the input array", () => {
    const copy = [...events];
    applyEventQuery(events, "severity_text: ERROR");
    expect(events).toEqual(copy);
  });

  // --- sigma mode: field: value pairs ---
  it("matches sigma field:value (case-insensitive substring)", () => {
    const r = applyEventQuery(events, "severity_text: error");
    expect(r.mode).toBe("sigma");
    expect(r.valid).toBe(true);
    expect(r.matched.map((e) => e.event_id)).toEqual(["b"]);
  });

  it("matches sigma field=value", () => {
    const r = applyEventQuery(events, "source_type=syslog");
    expect(r.mode).toBe("sigma");
    expect(r.matched.map((e) => e.event_id).sort()).toEqual(["a", "c"]);
  });

  it("ANDs multiple sigma pairs", () => {
    const r = applyEventQuery(events, "source_type: syslog, severity_text: fatal");
    expect(r.matched.map((e) => e.event_id)).toEqual(["a"]);
  });

  it("flags sigma with an unknown field as invalid (shows all + hint)", () => {
    const r = applyEventQuery(events, "nope: value");
    expect(r.valid).toBe(false);
    expect(r.matched).toHaveLength(events.length);
    expect(r.hint).toBeTruthy();
  });

  // --- sql mode: WHERE-like comparisons ---
  it("matches sql numeric >= comparison", () => {
    const r = applyEventQuery(events, "severity_id >= 4");
    expect(r.mode).toBe("sql");
    expect(r.matched.map((e) => e.event_id).sort()).toEqual(["a", "b"]);
  });

  it("matches sql string equality with quotes", () => {
    const r = applyEventQuery(events, "source_type = 'kafka'");
    expect(r.mode).toBe("sql");
    expect(r.matched.map((e) => e.event_id)).toEqual(["b"]);
  });

  it("matches sql contains operator", () => {
    const r = applyEventQuery(events, "message contains query");
    expect(r.matched.map((e) => e.event_id)).toEqual(["d"]);
  });

  it("matches sql != operator", () => {
    const r = applyEventQuery(events, "source_type != syslog");
    expect(r.matched.map((e) => e.event_id).sort()).toEqual(["b", "d"]);
  });

  it("flags sql with an unknown field as invalid", () => {
    const r = applyEventQuery(events, "bogus >= 1");
    expect(r.valid).toBe(false);
    expect(r.matched).toHaveLength(events.length);
    expect(r.hint).toBeTruthy();
  });

  it("matches sql <= operator", () => {
    const r = applyEventQuery(events, "severity_id <= 2");
    expect(r.matched.map((e) => e.event_id)).toEqual(["c"]);
  });

  it("matches sql < operator", () => {
    const r = applyEventQuery(events, "severity_id < 3");
    expect(r.matched.map((e) => e.event_id)).toEqual(["c"]);
  });

  it("matches sql > operator", () => {
    const r = applyEventQuery(events, "severity_id > 4");
    expect(r.matched.map((e) => e.event_id)).toEqual(["a"]);
  });

  it("flags an unparseable sql expression as invalid", () => {
    const r = applyEventQuery(events, "where >= 4");
    expect(r.valid).toBe(false);
    expect(r.matched).toHaveLength(events.length);
  });

  it("matches on event_id and template_id fields", () => {
    expect(applyEventQuery(events, "event_id: a").matched.map((e) => e.event_id)).toEqual(["a"]);
    expect(applyEventQuery(events, "template_id = 1").matched).toHaveLength(events.length);
  });

  it("flags an unparseable jq expression as invalid", () => {
    const r = applyEventQuery(events, ".source_type");
    expect(r.valid).toBe(false);
    expect(r.matched).toHaveLength(events.length);
  });

  it("flags an unknown jq field as invalid", () => {
    const r = applyEventQuery(events, '.bogus == "x"');
    expect(r.valid).toBe(false);
    expect(r.matched).toHaveLength(events.length);
  });

  // --- jq mode: .field == value / select ---
  it("matches jq .field == value", () => {
    const r = applyEventQuery(events, '.source_type == "kafka"');
    expect(r.mode).toBe("jq");
    expect(r.matched.map((e) => e.event_id)).toEqual(["b"]);
  });

  it("matches jq select(.severity_id >= 6)", () => {
    const r = applyEventQuery(events, "select(.severity_id >= 6)");
    expect(r.mode).toBe("jq");
    expect(r.matched.map((e) => e.event_id)).toEqual(["a"]);
  });

  // --- free text fallback ---
  it("matches free text as a substring over message", () => {
    const r = applyEventQuery(events, "login");
    expect(r.mode).toBe("text");
    expect(r.matched.map((e) => e.event_id)).toEqual(["c"]);
  });

  it("free text matches nothing gracefully (valid, empty)", () => {
    const r = applyEventQuery(events, "zzzznotpresent");
    expect(r.valid).toBe(true);
    expect(r.matched).toHaveLength(0);
  });
});

describe("countSeverities", () => {
  it("counts crit (>=6) and warn (>=4, <6)", () => {
    expect(countSeverities(events)).toEqual({ crit: 1, warn: 1 });
  });

  it("returns zeros for empty input", () => {
    expect(countSeverities([])).toEqual({ crit: 0, warn: 0 });
  });

  it("treats severity 5 as crit", () => {
    expect(countSeverities([ev({ severity_id: 5 })])).toEqual({ crit: 0, warn: 1 });
  });

  it("counts multiple of each", () => {
    const set = [
      ev({ severity_id: 6 }),
      ev({ severity_id: 6 }),
      ev({ severity_id: 4 }),
      ev({ severity_id: 1 }),
    ];
    expect(countSeverities(set)).toEqual({ crit: 2, warn: 1 });
  });
});
