import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { AlertDetailPanel } from "./AlertDetailPanel";
import type { Alert, AlertDetail } from "@/lib/types";

const base: Alert = {
  alert_id: "a1", timestamp_ns: 1n, alert_type: "sigma", rule_name: "r",
  severity: 13, risk_score: 0.5, entity_uuid: "u", entity_type: "ip",
  entity_value: "10.0.0.1", message: "m", mitre_tactics: ["TA0001"],
  mitre_techniques: ["T1078"], dedup_count: 1, source_type: "syslog",
};

const fetchMock = vi.fn();
vi.mock("@/lib/api", () => ({
  api: {
    get: (...a: unknown[]) => fetchMock("GET", ...a),
    post: (...a: unknown[]) => fetchMock("POST", ...a),
  },
  ApiError: class ApiError extends Error {},
}));

describe("AlertDetailPanel", () => {
  beforeEach(() => fetchMock.mockReset());

  it("fetches detail on mount and renders fields", async () => {
    const detail: AlertDetail = { ...base, contributing_events: [{event_id: "e1", timestamp_ns: 1, message: "ev"}] };
    fetchMock.mockResolvedValueOnce(detail);
    render(<AlertDetailPanel alert={base} onFeedback={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("ev")).toBeInTheDocument());
    expect(screen.getByText("TA0001")).toBeInTheDocument();
  });

  it("TP click POSTs feedback", async () => {
    fetchMock.mockResolvedValueOnce(base).mockResolvedValueOnce({});
    const onFeedback = vi.fn();
    render(<AlertDetailPanel alert={base} onFeedback={onFeedback} />);
    await waitFor(() => screen.getByRole("button", { name: /True positive/i }));
    fireEvent.click(screen.getByRole("button", { name: /True positive/i }));
    expect(onFeedback).toHaveBeenCalledWith("a1", "tp");
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("POST", "/api/v1/alerts/a1/feedback", { feedback: "tp" })
    );
  });
});
