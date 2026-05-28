/**
 * S-339: FeedbackPanel — TP/FP verdict + history block on the alert detail page.
 *
 * Unit-tests the panel in isolation: the click path delegates to
 * `submitFeedback` (covered by `lib/feedback.test.ts`), the pressed visual is
 * derived from the live store value, and the `FeedbackHistory` underneath
 * refreshes on `bumpFeedbackVersion`.
 */
import { render, screen, act, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useAlertStore } from "@/stores/alerts";
import type { Alert, FeedbackEvent, FeedbackHistoryResponse } from "@/lib/types";

const ALERT: Alert = {
  alert_id: "alert-x",
  timestamp_ns: 1n,
  alert_type: "sigma",
  rule_name: "r",
  severity: 3,
  risk_score: 0.5,
  entity_uuid: null,
  entity_type: null,
  entity_value: null,
  message: "",
  mitre_tactics: [],
  mitre_techniques: [],
  dedup_count: 1,
  feedback: "",
};

// ── Mock submitFeedback so the click path is observable without hitting the
// store's optimistic flow during tests of pressed-visual derivation. ─────────
const submitFeedbackMock = vi.fn();
vi.mock("@/lib/feedback", () => ({
  submitFeedback: (alertId: string, verdict: "tp" | "fp") =>
    submitFeedbackMock(alertId, verdict),
}));

// ── Mock the typed API client so the history fetch returns a deterministic
// payload per test. ──────────────────────────────────────────────────────────
let historyResponse: FeedbackHistoryResponse = {
  items: [],
  total: 0,
  page: 1,
  limit: 5,
  has_next: false,
};
const apiGetMock = vi.fn<
  (path: string, opts?: unknown) => Promise<FeedbackHistoryResponse>
>(async () => historyResponse);
vi.mock("@/lib/api", () => ({
  api: { get: (path: string, opts?: unknown) => apiGetMock(path, opts) },
  ApiError: class extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

import { FeedbackPanel } from "./FeedbackPanel";

const ev = (p: Partial<FeedbackEvent> = {}): FeedbackEvent => ({
  id: 1,
  feedback: "tp",
  note: "",
  origin: "dashboard",
  submitted_at_ns: 1_700_000_000_000_000_000n,
  ...p,
});

describe("FeedbackPanel (S-339)", () => {
  beforeEach(() => {
    useAlertStore.setState({
      alerts: [ALERT],
      feedbackVersion: {},
    });
    submitFeedbackMock.mockReset();
    apiGetMock.mockClear();
    historyResponse = {
      items: [],
      total: 0,
      page: 1,
      limit: 5,
      has_next: false,
    };
  });

  it("renders TP and FP buttons", () => {
    render(<FeedbackPanel alertId="alert-x" />);
    expect(
      screen.getByRole("button", { name: /true positive/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /false positive/i }),
    ).toBeInTheDocument();
  });

  it("clicking TP calls submitFeedback with (alertId, 'tp')", async () => {
    render(<FeedbackPanel alertId="alert-x" />);
    await userEvent.click(
      screen.getByRole("button", { name: /true positive/i }),
    );
    expect(submitFeedbackMock).toHaveBeenCalledWith("alert-x", "tp");
  });

  it("clicking FP calls submitFeedback with (alertId, 'fp')", async () => {
    render(<FeedbackPanel alertId="alert-x" />);
    await userEvent.click(
      screen.getByRole("button", { name: /false positive/i }),
    );
    expect(submitFeedbackMock).toHaveBeenCalledWith("alert-x", "fp");
  });

  it("reflects pressed visual from the live store feedback value", () => {
    useAlertStore.setState({
      alerts: [{ ...ALERT, feedback: "tp" }],
      feedbackVersion: {},
    });
    render(<FeedbackPanel alertId="alert-x" />);
    expect(
      screen.getByRole("button", { name: /true positive/i }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("button", { name: /false positive/i }),
    ).toHaveAttribute("aria-pressed", "false");
  });

  it("fetches history on mount with limit=5", async () => {
    render(<FeedbackPanel alertId="alert-x" />);
    await waitFor(() => {
      expect(apiGetMock).toHaveBeenCalled();
    });
    const firstCall = apiGetMock.mock.calls[0];
    expect(firstCall).toBeDefined();
    expect(firstCall?.[0]).toMatch(
      /\/api\/v1\/alerts\/alert-x\/feedback\?limit=5/,
    );
  });

  it("renders the history rows from the GET response", async () => {
    historyResponse = {
      items: [ev({ id: 1, feedback: "tp", origin: "cli" })],
      total: 1,
      page: 1,
      limit: 5,
      has_next: false,
    };
    render(<FeedbackPanel alertId="alert-x" />);
    await waitFor(() => {
      expect(screen.getByTestId("feedback-history-row")).toBeInTheDocument();
    });
  });

  it("re-fetches history when feedbackVersion bumps", async () => {
    render(<FeedbackPanel alertId="alert-x" />);
    await waitFor(() => expect(apiGetMock).toHaveBeenCalledTimes(1));
    act(() => {
      useAlertStore.getState().bumpFeedbackVersion("alert-x");
    });
    await waitFor(() => expect(apiGetMock).toHaveBeenCalledTimes(2));
  });

  it("shows '+N more' when total exceeds the displayed cap", async () => {
    historyResponse = {
      items: [
        ev({ id: 1 }),
        ev({ id: 2 }),
        ev({ id: 3 }),
        ev({ id: 4 }),
        ev({ id: 5 }),
      ],
      total: 12,
      page: 1,
      limit: 5,
      has_next: true,
    };
    render(<FeedbackPanel alertId="alert-x" />);
    await waitFor(() => {
      expect(screen.getByText(/\+7 more/i)).toBeInTheDocument();
    });
  });

  it("shows the empty placeholder when there is no history", async () => {
    render(<FeedbackPanel alertId="alert-x" />);
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled());
    expect(screen.getByText(/no feedback yet/i)).toBeInTheDocument();
  });

  it("does not crash when the history endpoint rejects", async () => {
    apiGetMock.mockRejectedValueOnce(new Error("offline"));
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(<FeedbackPanel alertId="alert-x" />);
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled());
    // Empty placeholder still renders; no unhandled rejection.
    expect(screen.getByText(/no feedback yet/i)).toBeInTheDocument();
    errSpy.mockRestore();
  });
});
