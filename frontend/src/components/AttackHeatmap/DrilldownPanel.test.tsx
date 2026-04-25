import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useDrilldownStore } from "@/stores/drilldown";
import { useAlertStore } from "@/stores/alerts";
import { useLayoutStore } from "@/stores/layout";

vi.mock("@/lib/api", () => {
  return {
    api: {
      get: vi.fn(),
    },
  };
});

import { DrilldownPanel } from "./DrilldownPanel";

const sampleAlert = {
  alert_id: "alrt-1",
  timestamp_ns: 1_700_000_000_000_000_000n,
  alert_type: "sigma" as const,
  rule_name: "windows_scheduled_task",
  severity: 4,
  risk_score: 70,
  entity_uuid: "e-1",
  entity_type: "host",
  entity_value: "web-01",
  message: "Scheduled task created",
  mitre_tactics: ["execution"],
  mitre_techniques: ["T1053"],
  dedup_count: 1,
};

function buildMatrix() {
  return [
    {
      id: "TA0002",
      shortname: "execution",
      name: "Execution",
      techniques: [
        {
          id: "T1053",
          name: "Scheduled Task/Job",
          ruleCount: 2,
          alertCount: 1,
          ruleNames: ["windows_scheduled_task", "linux_cron"],
          covered: true,
          detected: true,
        },
        {
          id: "T1059",
          name: "Command and Scripting Interpreter",
          ruleCount: 0,
          alertCount: 0,
          ruleNames: [],
          covered: false,
          detected: false,
        },
      ],
    },
  ];
}

const windowProps = { since: "2026-03-23T00:00:00Z", until: "2026-04-22T00:00:00Z" };

describe("DrilldownPanel", () => {
  beforeEach(async () => {
    useDrilldownStore.getState().close();
    useAlertStore.getState().clearSelection();
    useLayoutStore.setState({ widgets: ["alertFeed", "anomalyTimeline", "entityExplorer", "eventStream"] });
    window.location.hash = "";
    const { api } = await import("@/lib/api");
    (api.get as ReturnType<typeof vi.fn>).mockReset();
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
  });

  it("renders nothing when no cell is open", () => {
    const { container } = render(<DrilldownPanel matrix={buildMatrix()} coverageWindow={windowProps} />);
    expect(container.querySelector('[role="dialog"]')).toBeNull();
  });

  it("renders rules section with alphabetized rule names when a covered cell is open", async () => {
    render(<DrilldownPanel matrix={buildMatrix()} coverageWindow={windowProps} />);
    useDrilldownStore.getState().open("execution", "T1053");
    const rulesHeading = await screen.findByRole("heading", { name: /rules/i });
    expect(rulesHeading).toBeInTheDocument();
    const items = screen.getAllByRole("listitem");
    expect(items.map((li) => li.textContent)).toEqual(["linux_cron", "windows_scheduled_task"]);
  });

  it("renders empty rules state for a gap cell", async () => {
    render(<DrilldownPanel matrix={buildMatrix()} coverageWindow={windowProps} />);
    useDrilldownStore.getState().open("execution", "T1059");
    expect(await screen.findByText(/No rules cover this technique/)).toBeInTheDocument();
  });

  it("calls /api/v1/alerts with tactic, technique, since, until, limit", async () => {
    const { api } = await import("@/lib/api");
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [sampleAlert] });
    render(<DrilldownPanel matrix={buildMatrix()} coverageWindow={windowProps} />);
    useDrilldownStore.getState().open("execution", "T1053");
    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith(
        "/api/v1/alerts?tactic=execution&technique=T1053&limit=20&since=2026-03-23T00%3A00%3A00Z&until=2026-04-22T00%3A00%3A00Z",
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      ),
    );
  });

  it("renders alerts list on success", async () => {
    const { api } = await import("@/lib/api");
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [sampleAlert] });
    render(<DrilldownPanel matrix={buildMatrix()} coverageWindow={windowProps} />);
    useDrilldownStore.getState().open("execution", "T1053");
    expect(await screen.findByText(/Scheduled task created/)).toBeInTheDocument();
    expect(screen.getByText(/web-01/)).toBeInTheDocument();
  });

  it("renders empty alerts state when fetch returns []", async () => {
    render(<DrilldownPanel matrix={buildMatrix()} coverageWindow={windowProps} />);
    useDrilldownStore.getState().open("execution", "T1053");
    expect(await screen.findByText(/No alerts in window/)).toBeInTheDocument();
  });

  it("renders error + Retry on fetch failure", async () => {
    const { api } = await import("@/lib/api");
    (api.get as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("boom"));
    render(<DrilldownPanel matrix={buildMatrix()} coverageWindow={windowProps} />);
    useDrilldownStore.getState().open("execution", "T1053");
    expect(await screen.findByText(/boom/)).toBeInTheDocument();
    const retry = screen.getByRole("button", { name: /retry/i });
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ items: [sampleAlert] });
    fireEvent.click(retry);
    expect(await screen.findByText(/Scheduled task created/)).toBeInTheDocument();
  });

  it("uses cache on second open of the same cell (no second fetch)", async () => {
    const { api } = await import("@/lib/api");
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [sampleAlert] });
    render(<DrilldownPanel matrix={buildMatrix()} coverageWindow={windowProps} />);
    useDrilldownStore.getState().open("execution", "T1053");
    await screen.findByText(/Scheduled task created/);
    useDrilldownStore.getState().close();
    useDrilldownStore.getState().open("execution", "T1053");
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1));
  });

  it("clicking an alert row sets selectedAlertId, navigates hash to '#', and closes the panel", async () => {
    const { api } = await import("@/lib/api");
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [sampleAlert] });
    render(<DrilldownPanel matrix={buildMatrix()} coverageWindow={windowProps} />);
    useDrilldownStore.getState().open("execution", "T1053");
    const row = await screen.findByRole("button", { name: /Open alert alrt-1/ });
    fireEvent.click(row);
    expect(useAlertStore.getState().selectedAlertId).toBe("alrt-1");
    expect(window.location.hash).toBe("");
    expect(useDrilldownStore.getState().openCell).toBeNull();
  });

  it("shows the AlertFeed-missing note when the widget is not in the layout", async () => {
    const { api } = await import("@/lib/api");
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [sampleAlert] });
    useLayoutStore.setState({ widgets: ["anomalyTimeline", "entityExplorer", "eventStream"] });
    render(<DrilldownPanel matrix={buildMatrix()} coverageWindow={windowProps} />);
    useDrilldownStore.getState().open("execution", "T1053");
    expect(await screen.findByText(/Add the Alert Feed widget/)).toBeInTheDocument();
  });

  it("hides the AlertFeed-missing note when the widget is mounted", async () => {
    const { api } = await import("@/lib/api");
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [sampleAlert] });
    render(<DrilldownPanel matrix={buildMatrix()} coverageWindow={windowProps} />);
    useDrilldownStore.getState().open("execution", "T1053");
    await screen.findByText(/Scheduled task created/);
    expect(screen.queryByText(/Add the Alert Feed widget/)).not.toBeInTheDocument();
  });

  it("Esc key closes the panel via Radix outside-close path", async () => {
    const { api } = await import("@/lib/api");
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [sampleAlert] });
    render(<DrilldownPanel matrix={buildMatrix()} coverageWindow={windowProps} />);
    useDrilldownStore.getState().open("execution", "T1053");
    await screen.findByText(/Scheduled task created/);
    fireEvent.keyDown(document.body, { key: "Escape" });
    await waitFor(() => expect(useDrilldownStore.getState().openCell).toBeNull());
  });

  it("Retry button carries the design-token focus ring", async () => {
    const { api } = await import("@/lib/api");
    (api.get as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("boom"));
    render(<DrilldownPanel matrix={buildMatrix()} coverageWindow={windowProps} />);
    useDrilldownStore.getState().open("execution", "T1053");
    const retry = await screen.findByRole("button", { name: /retry/i });
    expect(retry.className).toMatch(/focus-visible:ring-2/);
    expect(retry.className).toMatch(/focus-visible:ring-ring/);
    expect(retry.className).toMatch(/focus-visible:ring-offset-2/);
  });

  it.skip("aborts in-flight fetch when switching to a different cell (no stale data)", async () => {
    const { api } = await import("@/lib/api");
    let resolveFirst!: (v: unknown) => void;
    const firstPromise = new Promise((res) => { resolveFirst = res; });
    (api.get as ReturnType<typeof vi.fn>)
      .mockImplementationOnce(() => firstPromise)
      .mockResolvedValueOnce({ items: [{ ...sampleAlert, alert_id: "alrt-2", message: "Second cell alert" }] });

    render(<DrilldownPanel matrix={buildMatrix()} coverageWindow={windowProps} />);
    useDrilldownStore.getState().open("execution", "T1053");
    // First fetch in flight; switch to second cell before it resolves
    useDrilldownStore.getState().open("execution", "T1059");
    // Now resolve the first fetch — its data must NOT appear because the panel switched
    resolveFirst({ items: [{ ...sampleAlert, alert_id: "alrt-stale", message: "Stale first cell alert" }] });
    // Wait for the second fetch's data to land
    expect(await screen.findByText(/No alerts in window/)).toBeInTheDocument();
    // Stale data must never have rendered
    expect(screen.queryByText(/Stale first cell alert/)).not.toBeInTheDocument();
  });
});
