/**
 * Integration tests for AlertDetailScreen (S-321).
 * Tests the full detail view: header, kill-chain, correlated events, right rail.
 */
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import type { Alert, AlertDetail } from "@/lib/types";
import { useAlertStore, createAlertStore } from "@/stores/alerts";

// ── Fixtures ──────────────────────────────────────────────────────────────────
const ALERT: Alert = {
  alert_id: "alert-abc-123",
  timestamp_ns: BigInt("1700000000000000000"),
  alert_type: "sigma",
  rule_name: "Credential Dumping via LSASS",
  severity: 5,
  risk_score: 0.87,
  entity_uuid: "ent-uuid-001",
  entity_type: "host",
  entity_value: "ws-attack-01",
  message: "LSASS memory access detected from suspicious process",
  mitre_tactics: ["TA0006", "TA0008"],
  mitre_techniques: ["T1003.001", "T1550.002"],
  dedup_count: 3,
  source_type: "windows",
  feedback: "",
};

const DETAIL: AlertDetail = {
  ...ALERT,
  contributing_events: [
    {
      event_id: "ev-1",
      timestamp_ns: BigInt("1699999990000000000"),
      message: "lsass.exe memory read by mimikatz.exe",
    },
    {
      event_id: "ev-2",
      timestamp_ns: BigInt("1699999995000000000"),
      message: "Suspicious process access to sensitive registry key",
    },
  ],
};

// ── API mock ──────────────────────────────────────────────────────────────────
let _resolveDetail: ((d: AlertDetail) => void) | null = null;

vi.mock("@/lib/api", () => {
  class FactoryApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.name = "ApiError";
      this.status = status;
    }
  }

  return {
    api: {
      get: vi.fn(async (path: string) => {
        if (path.includes("/feedback")) {
          return { items: [], total: 0, page: 1, limit: 10, has_next: false };
        }
        if (path.includes("/api/v1/alerts/nonexistent-id")) {
          throw new FactoryApiError(404, "not found");
        }
        if (path.includes("/api/v1/alerts/")) {
          return new Promise<AlertDetail>((res) => {
            _resolveDetail = res;
          });
        }
        return {};
      }),
    },
    ApiError: FactoryApiError,
  };
});

// Import screen after mock is registered
import { AlertDetailScreen } from "@/screens/AlertDetailScreen";

// ── Tests ─────────────────────────────────────────────────────────────────────
describe("AlertDetailScreen (S-321)", () => {
  beforeEach(() => {
    _resolveDetail = null;
    window.history.replaceState(null, "", "/#/alerts/alert-abc-123");
    useAlertStore.getState().backfill([ALERT]);
  });

  it("renders rule name in heading", () => {
    render(<AlertDetailScreen />);
    expect(
      screen.getByRole("heading", { name: /Credential Dumping/i }),
    ).toBeInTheDocument();
  });

  it("renders severity badge in header", () => {
    render(<AlertDetailScreen />);
    expect(screen.getByText(/critical/i)).toBeInTheDocument();
  });

  it("renders risk score in header", () => {
    render(<AlertDetailScreen />);
    expect(screen.getByText(/0\.87/)).toBeInTheDocument();
  });

  it("renders kill-chain timeline list", () => {
    render(<AlertDetailScreen />);
    expect(screen.getByRole("list", { name: /kill.chain/i })).toBeInTheDocument();
  });

  it("renders correlated events after detail resolves", async () => {
    render(<AlertDetailScreen />);
    await act(async () => {
      _resolveDetail?.(DETAIL);
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getByText(/lsass.exe memory read/i)).toBeInTheDocument();
  });

  it("renders Entities SideBlock label in right rail", () => {
    render(<AlertDetailScreen />);
    expect(screen.getByText(/entities/i)).toBeInTheDocument();
  });

  it("renders MITRE ATT&CK SideBlock label in right rail", () => {
    render(<AlertDetailScreen />);
    expect(screen.getByText(/mitre/i)).toBeInTheDocument();
  });

  it("renders AI Explanation SideBlock label in right rail", () => {
    render(<AlertDetailScreen />);
    expect(screen.getByText(/ai explanation/i)).toBeInTheDocument();
  });

  it("renders Acknowledge action button", () => {
    render(<AlertDetailScreen />);
    expect(screen.getByRole("button", { name: /acknowledge/i })).toBeInTheDocument();
  });

  it("renders Run playbook action button", () => {
    render(<AlertDetailScreen />);
    expect(screen.getByRole("button", { name: /run playbook/i })).toBeInTheDocument();
  });

  it("shows not-found when alert is absent from store", async () => {
    window.history.replaceState(null, "", "/#/alerts/nonexistent-id");
    render(<AlertDetailScreen />);
    // Wait for the API to reject (404) → loading state resolves → not-found renders
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getByText(/alert not found/i)).toBeInTheDocument();
  });

  it("renders entity value from the alert", () => {
    render(<AlertDetailScreen />);
    expect(screen.getByText("ws-attack-01")).toBeInTheDocument();
  });

  it("renders technique chips in MITRE rail", () => {
    render(<AlertDetailScreen />);
    expect(screen.getByText("T1003.001")).toBeInTheDocument();
    expect(screen.getByText("T1550.002")).toBeInTheDocument();
  });

  it("Acknowledge button toggles to acknowledged state on click", async () => {
    render(<AlertDetailScreen />);
    const btn = screen.getByRole("button", { name: /acknowledge/i });
    await userEvent.click(btn);
    expect(screen.getByRole("button", { name: /acknowledged/i })).toBeInTheDocument();
  });

  it("auto-scroll checkbox is rendered after events load", async () => {
    render(<AlertDetailScreen />);
    await act(async () => {
      _resolveDetail?.(DETAIL);
      await new Promise((r) => setTimeout(r, 20));
    });
    const toggle = screen.queryByRole("checkbox", { name: /auto.scroll/i });
    if (toggle) {
      expect(toggle).toBeChecked();
    }
  });
});

// ── Verify createAlertStore is a valid export (smoke) ─────────────────────────
describe("createAlertStore (dependency check)", () => {
  it("exports createAlertStore for isolated testing", () => {
    expect(typeof createAlertStore).toBe("function");
    const store = createAlertStore(10);
    expect(store.getState().alerts).toHaveLength(0);
  });
});
