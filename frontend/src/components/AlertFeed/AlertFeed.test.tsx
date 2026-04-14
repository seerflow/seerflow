import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import { AlertFeed } from "./AlertFeed";

const fetchMock = vi.fn();
vi.mock("@/lib/api", () => ({
  api: { get: (...a: unknown[]) => fetchMock("GET", ...a), post: vi.fn() },
  ApiError: class ApiError extends Error {},
}));

class MockWS {
  static last: MockWS | null = null;
  readyState = 0;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  sent: unknown[] = [];
  constructor() { MockWS.last = this; }
  send(d: string) { this.sent.push(JSON.parse(d)); }
  close() { this.readyState = 3; this.onclose?.(); }
  _open() { this.readyState = 1; this.onopen?.(); }
  _msg(m: unknown) { this.onmessage?.({ data: JSON.stringify(m) }); }
}

describe("AlertFeed integration", () => {
  beforeEach(() => { vi.stubGlobal("WebSocket", MockWS as unknown as typeof WebSocket); fetchMock.mockReset(); });
  afterEach(() => vi.unstubAllGlobals());

  it("warm-up then live alert appears at top", async () => {
    fetchMock.mockResolvedValueOnce({ items: [
      { alert_id: "warm", timestamp_ns: 1, alert_type: "ml", rule_name: "warmup-rule",
        severity: 9, risk_score: 0.1, entity_uuid: null, entity_type: null,
        entity_value: null, message: "", mitre_tactics: [], mitre_techniques: [],
        dedup_count: 1, source_type: "syslog" },
    ] });
    render(<AlertFeed />);
    await waitFor(() => expect(screen.getByText("warmup-rule")).toBeInTheDocument());
    act(() => {
      MockWS.last!._open();
      MockWS.last!._msg({ type: "alert", data: {
        alert_id: "live", timestamp_ns: 2, alert_type: "sigma", rule_name: "live-rule",
        severity: 17, risk_score: 0.9, entity_uuid: null, entity_type: null,
        entity_value: null, message: "", mitre_tactics: [], mitre_techniques: [],
        dedup_count: 1, source_type: "syslog",
      } });
    });
    expect(screen.getByText("live-rule")).toBeInTheDocument();
  });
});
