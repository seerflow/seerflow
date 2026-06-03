import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import type { Alert } from "@/lib/types";
import { RecentAlertsList } from "./RecentAlertsList";

// Mock formatRelative
vi.mock("@/lib/relativeTime", () => ({
  formatRelative: vi.fn((ts: bigint | number) => {
    void ts;
    return "12s ago";
  }),
}));

function makeAlert(overrides: Partial<Alert> = {}): Alert {
  return {
    alert_id: `alert-${Math.random().toString(36).slice(2)}`,
    timestamp_ns: BigInt(Date.now()) * 1_000_000n,
    alert_type: "sigma",
    rule_name: "test_rule",
    severity: 5,
    risk_score: 0.9,
    entity_uuid: null,
    entity_type: null,
    entity_value: "test-entity",
    message: "Test alert",
    mitre_tactics: [],
    mitre_techniques: [],
    dedup_count: 1,
    ...overrides,
  };
}

describe("RecentAlertsList", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the section heading", () => {
    render(<RecentAlertsList alerts={[]} />);
    expect(screen.getByText("Recent alerts")).toBeInTheDocument();
  });

  it("shows empty state when no alerts", () => {
    render(<RecentAlertsList alerts={[]} />);
    expect(screen.getByTestId("recent-alerts-empty")).toBeInTheDocument();
  });

  it("renders up to 5 alert rows", () => {
    const alerts = Array.from({ length: 7 }, (_, i) =>
      makeAlert({ alert_id: `alert-${i}`, rule_name: `rule_${i}` }),
    );
    render(<RecentAlertsList alerts={alerts} />);
    expect(screen.getAllByTestId(/alert-row-/)).toHaveLength(5);
  });

  it("renders alert row with rule name in mono", () => {
    const alert = makeAlert({ rule_name: "ssh_brute_force" });
    render(<RecentAlertsList alerts={[alert]} />);
    expect(screen.getByText("ssh_brute_force")).toBeInTheDocument();
  });

  it("renders entity value when present", () => {
    const alert = makeAlert({ entity_value: "root@10.0.1.42" });
    render(<RecentAlertsList alerts={[alert]} />);
    expect(screen.getByText("root@10.0.1.42")).toBeInTheDocument();
  });

  it("renders severity dot with crit color for critical severity", () => {
    const alert = makeAlert({ severity: 5 });
    render(<RecentAlertsList alerts={[alert]} />);
    const dot = screen.getByTestId(`severity-dot-${alert.alert_id}`);
    expect(dot).toBeInTheDocument();
    expect(dot).toHaveAttribute("data-severity", "crit");
  });

  it("renders severity dot with warn color for medium severity", () => {
    const alert = makeAlert({ severity: 3 });
    render(<RecentAlertsList alerts={[alert]} />);
    const dot = screen.getByTestId(`severity-dot-${alert.alert_id}`);
    expect(dot).toHaveAttribute("data-severity", "warn");
  });

  it("renders risk score", () => {
    const alert = makeAlert({ risk_score: 0.94 });
    render(<RecentAlertsList alerts={[alert]} />);
    expect(screen.getByText("0.94")).toBeInTheDocument();
  });

  it("renders relative time", () => {
    const alert = makeAlert();
    render(<RecentAlertsList alerts={[alert]} />);
    expect(screen.getByText("12s ago")).toBeInTheDocument();
  });

  it("renders view-all link with total count", () => {
    const alerts = Array.from({ length: 3 }, (_, i) =>
      makeAlert({ alert_id: `a${i}` }),
    );
    render(<RecentAlertsList alerts={alerts} totalCount={17} />);
    expect(screen.getByText(/view all 17/i)).toBeInTheDocument();
  });
});
