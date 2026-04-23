import { describe, expect, it } from "vitest";
import { isAlert, isLiveEvent, type Alert, type LiveEvent } from "./types";

const alert: Alert = {
  alert_id: "a-1",
  timestamp_ns: 1n,
  alert_type: "ml",
  rule_name: "r",
  severity: 3,
  risk_score: 0.5,
  entity_uuid: null,
  entity_type: null,
  entity_value: null,
  message: "m",
  mitre_tactics: [],
  mitre_techniques: [],
  dedup_count: 0,
};

const event: LiveEvent = {
  event_id: "e-1",
  timestamp_ns: 1n,
  observed_ns: 1n,
  severity_id: 3,
  severity_text: "medium",
  source_type: "syslog",
  message: "m",
  template_id: 0,
  entity_refs: [],
  entity_summary: {},
};

describe("isAlert", () => {
  it("accepts Alert shape", () => { expect(isAlert(alert)).toBe(true); });
  it("rejects LiveEvent shape", () => { expect(isAlert(event)).toBe(false); });
  it("rejects null", () => { expect(isAlert(null)).toBe(false); });
  it("rejects undefined", () => { expect(isAlert(undefined)).toBe(false); });
  it("rejects primitives", () => {
    expect(isAlert("x")).toBe(false);
    expect(isAlert(0)).toBe(false);
  });
  it("rejects empty object", () => { expect(isAlert({})).toBe(false); });
});

describe("isLiveEvent", () => {
  it("accepts LiveEvent shape", () => { expect(isLiveEvent(event)).toBe(true); });
  it("rejects Alert shape", () => { expect(isLiveEvent(alert)).toBe(false); });
  it("rejects null", () => { expect(isLiveEvent(null)).toBe(false); });
  it("rejects undefined", () => { expect(isLiveEvent(undefined)).toBe(false); });
  it("rejects empty object", () => { expect(isLiveEvent({})).toBe(false); });
});
