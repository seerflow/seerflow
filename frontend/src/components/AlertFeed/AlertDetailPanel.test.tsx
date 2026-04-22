import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { AlertDetailPanel } from "./AlertDetailPanel";
import type { Alert, AlertDetail } from "@/lib/types";
import { useAlertStore } from "@/stores/alerts";

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

const submitMock = vi.fn();
vi.mock("@/lib/feedback", () => ({
  submitFeedback: (...a: unknown[]) => submitMock(...a),
}));

const sampleHistory = {
  items: [
    {
      feedback: "tp",
      note: "",
      origin: "cli",
      submitted_at_ns: "1700000000000000000",
    },
  ],
  total: 1, page: 1, limit: 50, has_next: false,
};

function setupMocks(detail: AlertDetail): void {
  fetchMock.mockImplementation((method: string, url: string) => {
    if (method === "GET" && typeof url === "string" && url.endsWith("/feedback")) {
      return Promise.resolve(sampleHistory);
    }
    if (method === "GET") {
      return Promise.resolve(detail);
    }
    return Promise.resolve({});
  });
}

describe("AlertDetailPanel", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    submitMock.mockReset();
    useAlertStore.setState({ feedbackVersion: {} });
  });

  it("fetches detail on mount and renders fields", async () => {
    const detail: AlertDetail = { ...base, contributing_events: [{event_id: "e1", timestamp_ns: 1n, message: "ev"}] };
    setupMocks(detail);
    render(<AlertDetailPanel alert={base} onFeedback={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("ev")).toBeInTheDocument());
    expect(screen.getByText("TA0001")).toBeInTheDocument();
  });

  it("TP click invokes shared submitFeedback (S-066)", async () => {
    const detail: AlertDetail = { ...base };
    setupMocks(detail);
    render(<AlertDetailPanel alert={base} onFeedback={vi.fn()} />);
    await waitFor(() => screen.getByRole("button", { name: /True positive/i }));
    fireEvent.click(screen.getByRole("button", { name: /True positive/i }));
    expect(submitMock).toHaveBeenCalledWith("a1", "tp");
  });

  it("fetches history on mount and renders rows (S-066)", async () => {
    const detail: AlertDetail = { ...base };
    setupMocks(detail);
    render(<AlertDetailPanel alert={base} onFeedback={vi.fn()} />);
    await waitFor(() => expect(screen.getByTestId("feedback-history-row")).toBeInTheDocument());
  });

  it("refetches history when feedbackVersion bumps (S-066)", async () => {
    const detail: AlertDetail = { ...base };
    setupMocks(detail);
    render(<AlertDetailPanel alert={base} onFeedback={vi.fn()} />);
    await waitFor(() => expect(screen.getByTestId("feedback-history-row")).toBeInTheDocument());

    const before = fetchMock.mock.calls.filter(
      (call: unknown[]) => typeof call[1] === "string" && (call[1] as string).endsWith("/feedback"),
    ).length;
    useAlertStore.getState().bumpFeedbackVersion("a1");
    await waitFor(() => {
      const after = fetchMock.mock.calls.filter(
        (call: unknown[]) => typeof call[1] === "string" && (call[1] as string).endsWith("/feedback"),
      ).length;
      expect(after).toBe(before + 1);
    });
  });
});
