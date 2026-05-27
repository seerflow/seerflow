import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { Sidebar } from "./Sidebar";
import { useAlertStore } from "@/stores/alerts";
import { useStatusStore } from "@/stores/status";
import { DEMO_UPTIME_LABEL, DEMO_EVENTS_PER_SEC } from "@/lib/liveStats";

describe("Sidebar", () => {
  beforeEach(() => {
    useAlertStore.setState({ alerts: [] });
    useStatusStore.setState({ pipelineOnline: false, uptimeLabel: "—", evPerSec: 0 });
  });

  it("renders all 10 nav items", () => {
    render(<Sidebar activeRoute="overview" onNavigate={vi.fn()} />);
    expect(screen.getByText("Overview")).toBeInTheDocument();
    expect(screen.getByText("Alerts")).toBeInTheDocument();
    expect(screen.getByText("Events")).toBeInTheDocument();
    expect(screen.getByText("Entities")).toBeInTheDocument();
    expect(screen.getByText("ATT&CK")).toBeInTheDocument();
    expect(screen.getByText("Hunt")).toBeInTheDocument();
    expect(screen.getByText("Sigma rules")).toBeInTheDocument();
    expect(screen.getByText("Receivers")).toBeInTheDocument();
    expect(screen.getByText("Models")).toBeInTheDocument();
    expect(screen.getByText("Settings")).toBeInTheDocument();
  });

  it("renders all three group labels", () => {
    render(<Sidebar activeRoute="overview" onNavigate={vi.fn()} />);
    expect(screen.getByText("Monitor")).toBeInTheDocument();
    expect(screen.getByText("Investigate")).toBeInTheDocument();
    expect(screen.getByText("Configure")).toBeInTheDocument();
  });

  it("active item has data-active attribute", () => {
    render(<Sidebar activeRoute="alerts" onNavigate={vi.fn()} />);
    const alertsItem = screen.getByTestId("nav-item-alerts");
    expect(alertsItem).toHaveAttribute("data-active", "true");
  });

  it("non-active items do not have data-active=true", () => {
    render(<Sidebar activeRoute="overview" onNavigate={vi.fn()} />);
    const alertsItem = screen.getByTestId("nav-item-alerts");
    expect(alertsItem).not.toHaveAttribute("data-active", "true");
  });

  it("Alerts item shows a badge element (0 when no alerts)", () => {
    render(<Sidebar activeRoute="overview" onNavigate={vi.fn()} />);
    // The badge should be there with count 0
    const badge = screen.getByTestId("alerts-count-badge");
    expect(badge).toBeInTheDocument();
    expect(badge.textContent).toBe("0");
  });

  it("Alerts badge shows live count from alerts store", () => {
    useAlertStore.setState({
      alerts: [
        {
          alert_id: "a1",
          timestamp_ns: BigInt(0),
          alert_type: "sigma",
          rule_name: "test",
          severity: 5,
          risk_score: 0.9,
          entity_uuid: null,
          entity_type: null,
          entity_value: null,
          message: "test",
          mitre_tactics: [],
          mitre_techniques: [],
          dedup_count: 1,
        },
      ],
    });
    render(<Sidebar activeRoute="overview" onNavigate={vi.fn()} />);
    const badge = screen.getByTestId("alerts-count-badge");
    expect(badge.textContent).toBe("1");
  });

  it("header renders brand mark (aria-hidden img)", () => {
    const { container } = render(<Sidebar activeRoute="overview" onNavigate={vi.fn()} />);
    const img = container.querySelector('img[aria-hidden="true"]');
    expect(img).not.toBeNull();
  });

  it("header renders 'seerflow' text", () => {
    render(<Sidebar activeRoute="overview" onNavigate={vi.fn()} />);
    expect(screen.getByText("seerflow")).toBeInTheDocument();
  });

  it("header renders version badge", () => {
    render(<Sidebar activeRoute="overview" onNavigate={vi.fn()} />);
    expect(screen.getByTestId("version-badge")).toBeInTheDocument();
  });

  it("footer renders 'pipeline online' when pipelineOnline=true", () => {
    useStatusStore.setState({ pipelineOnline: true, uptimeLabel: "4d 12h", evPerSec: 100 });
    render(<Sidebar activeRoute="overview" onNavigate={vi.fn()} />);
    expect(screen.getByText(/pipeline online/i)).toBeInTheDocument();
  });

  it("footer renders 'pipeline offline' when pipelineOnline=false", () => {
    useStatusStore.setState({ pipelineOnline: false, uptimeLabel: "—", evPerSec: 0 });
    render(<Sidebar activeRoute="overview" onNavigate={vi.fn()} />);
    expect(screen.getByText(/pipeline offline/i)).toBeInTheDocument();
  });

  it("footer health reads live uptime / ev-s from the store (S-328)", () => {
    useStatusStore.setState({ pipelineOnline: true, uptimeLabel: "9d 2h", evPerSec: 9001 });
    render(<Sidebar activeRoute="overview" onNavigate={vi.fn()} />);
    const health = screen.getByTestId("sidebar-health");
    expect(health).toHaveTextContent("9d 2h");
    expect(health).toHaveTextContent("9,001");
  });

  it("footer health falls back to demo numbers when no live source connected (S-328 AC2/AC5)", () => {
    useStatusStore.setState({ pipelineOnline: false, uptimeLabel: "—", evPerSec: 0 });
    render(<Sidebar activeRoute="overview" onNavigate={vi.fn()} />);
    const health = screen.getByTestId("sidebar-health");
    expect(health).toHaveTextContent(DEMO_UPTIME_LABEL);
    expect(health).toHaveTextContent(DEMO_EVENTS_PER_SEC.toLocaleString());
  });

  it("clicking a nav item calls onNavigate with the route", () => {
    const onNavigate = vi.fn();
    render(<Sidebar activeRoute="overview" onNavigate={onNavigate} />);
    fireEvent.click(screen.getByTestId("nav-item-alerts"));
    expect(onNavigate).toHaveBeenCalledWith("alerts");
  });
});
