import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { AlertDetailPanel } from "./AlertDetailPanel";
import type { Alert, AlertDetail } from "@/lib/types";
import { useAlertStore } from "@/stores/alerts";
import { validateOrDropItem } from "@/lib/schemas";

const base: Alert = {
  alert_id: "a1", timestamp_ns: 1n, alert_type: "sigma", rule_name: "r",
  severity: 5, risk_score: 0.5, entity_uuid: "u", entity_type: "ip",
  entity_value: "10.0.0.1", message: "m", mitre_tactics: ["TA0001"],
  mitre_techniques: ["T1078"], dedup_count: 1, source_type: "syslog",
};

const fetchMock = vi.fn();
vi.mock("@/lib/api", async () => {
  const valibot = await import("valibot");
  class MockApiError extends Error {
    status: number;
    cause: unknown;
    constructor(status: number, message: string, cause?: unknown) {
      super(message);
      this.status = status;
      this.cause = cause;
    }
  }
  return {
    api: {
      // Mimic api.ts::request for both branches:
      //   - scalar-schema (no itemsKey): run `v.safeParse(schema, body)` and
      //     throw ApiError(0, "response-schema-fail: …") on violation.
      //   - schema + itemsKey === "items": iterate raw[itemsKey] and per-row
      //     drop invalid entries (S-210 — mirrors EventStream.test.tsx).
      get: async (path: string, opts?: { schema?: unknown; itemsKey?: string }) => {
        const res = await fetchMock("GET", path, opts);
        if (opts?.schema && opts?.itemsKey === "items") {
          const list = (res as Record<string, unknown>)[opts.itemsKey];
          if (Array.isArray(list)) {
            const kind = `rest:${path.split("?")[0]}`;
            const items = list
              .map(item => validateOrDropItem(opts.schema as Parameters<typeof validateOrDropItem>[0], item, kind))
              .filter((x): x is NonNullable<typeof x> => x !== null);
            return { ...(res as object), [opts.itemsKey]: items };
          }
        }
        if (opts?.schema && !opts?.itemsKey) {
          const parsed = valibot.safeParse(
            opts.schema as Parameters<typeof valibot.safeParse>[0],
            res,
          );
          if (!parsed.success) {
            throw new MockApiError(
              0,
              `response-schema-fail: ${parsed.issues.map(i => i.message).join("; ")}`,
            );
          }
          return parsed.output;
        }
        return res;
      },
      post: (...a: unknown[]) => fetchMock("POST", ...a),
    },
    ApiError: MockApiError,
  };
});

const submitMock = vi.fn();
vi.mock("@/lib/feedback", () => ({
  submitFeedback: (...a: unknown[]) => submitMock(...a),
}));

const sampleHistory = {
  items: [
    {
      id: 1,
      feedback: "tp",
      note: "",
      origin: "cli",
      submitted_at_ns: 1_700_000_000_000_000_000n,
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
    render(<AlertDetailPanel alert={base} />);
    await waitFor(() => expect(screen.getByText("ev")).toBeInTheDocument());
    expect(screen.getByText("TA0001")).toBeInTheDocument();
  });

  it("TP click invokes shared submitFeedback (S-066)", async () => {
    const detail: AlertDetail = { ...base };
    setupMocks(detail);
    render(<AlertDetailPanel alert={base} />);
    await waitFor(() => screen.getByRole("button", { name: /True positive/i }));
    fireEvent.click(screen.getByRole("button", { name: /True positive/i }));
    expect(submitMock).toHaveBeenCalledWith("a1", "tp");
  });

  it("fetches history on mount and renders rows (S-066)", async () => {
    const detail: AlertDetail = { ...base };
    setupMocks(detail);
    render(<AlertDetailPanel alert={base} />);
    await waitFor(() => expect(screen.getByTestId("feedback-history-row")).toBeInTheDocument());
  });

  it("surfaces schema-fail error when the REST detail violates AlertDetailSchema (S-191 I-1)", async () => {
    // severity 999 violates AlertDetailSchema (OCSF severity must be 0..6).
    // The schema-opt-in mock throws ApiError(0, "response-schema-fail: …") which
    // flows through the existing setErr branch and renders role=alert.
    const malformed = { ...base, severity: 999 } as unknown as AlertDetail;
    setupMocks(malformed);
    render(<AlertDetailPanel alert={base} />);
    const errNode = await screen.findByRole("alert");
    expect(errNode.textContent).toMatch(/response-schema-fail/);
    // Loading + success paths must not render when schema fails.
    expect(screen.queryByText("r")).toBeNull();
  });

  it("drops malformed feedback history items via schema validation (S-210)", async () => {
    const detail: AlertDetail = { ...base };
    // submitted_at_ns must be a non-negative bigint per FeedbackEventSchema.
    // The mock above runs schema+itemsKey through per-row safeParse, dropping
    // invalid rows. End result: only the valid item renders.
    const malformedHistory = {
      items: [
        {
          id: 1, feedback: "tp", note: "", origin: "cli",
          submitted_at_ns: 1_700_000_000_000_000_000n,
        },
        {
          // feedback="garbage" violates the picklist — must be dropped.
          id: 2, feedback: "garbage", note: "", origin: "cli",
          submitted_at_ns: 1_700_000_000_000_000_001n,
        },
      ],
      total: 2, page: 1, limit: 50, has_next: false,
    };
    fetchMock.mockImplementation((method: string, url: string) => {
      if (method === "GET" && typeof url === "string" && url.endsWith("/feedback")) {
        return Promise.resolve(malformedHistory);
      }
      return Promise.resolve(detail);
    });
    render(<AlertDetailPanel alert={base} />);
    await waitFor(() => {
      expect(screen.getAllByTestId("feedback-history-row")).toHaveLength(1);
    });
  });

  it("refetches history when feedbackVersion bumps (S-066)", async () => {
    const detail: AlertDetail = { ...base };
    setupMocks(detail);
    render(<AlertDetailPanel alert={base} />);
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
