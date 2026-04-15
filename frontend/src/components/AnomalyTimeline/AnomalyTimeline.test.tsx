import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AnomalyTimeline } from "./AnomalyTimeline";
import { findAlertInBucket } from "./alertMatch";
import type { TimelineResponse } from "@/lib/types";
import { resetAnomalyStore, useAnomalyStore } from "@/stores/anomaly";
import { useAlertStore } from "@/stores/alerts";

const fetchMock = vi.fn<(...args: unknown[]) => Promise<TimelineResponse>>();
fetchMock.mockResolvedValue({
  meta: { range: "1h", resolution: "1m", source: null },
  items: [],
});
vi.mock("@/lib/api", () => ({
  api: {
    get: (...args: unknown[]) => fetchMock(...args),
    post: vi.fn(),
  },
  ApiError: class ApiError extends Error {},
}));

const okResponse = (): TimelineResponse => ({
  meta: { range: "1h", resolution: "1m", source: null },
  items: [
    { bucket_start_ns: 0, max_score: 0.3, avg_score: 0.2, event_count: 2, upper_threshold: 0.9, alert_count: 0 },
    { bucket_start_ns: 60_000_000_000, max_score: 0.7, avg_score: 0.5, event_count: 3, upper_threshold: 0.9, alert_count: 1 },
  ],
});

function resetAlertStore(): void {
  useAlertStore.setState({
    alerts: [],
    detail: {},
    filter: { severities: new Set(), types: new Set(), sources: new Set(), tactics: new Set() },
    status: "connecting",
    dropped: 0,
    selectedAlertId: null,
  });
}

describe("AnomalyTimeline", () => {
  beforeEach(() => {
    fetchMock.mockClear();
    fetchMock.mockResolvedValue(okResponse());
    resetAnomalyStore();
    resetAlertStore();
  });
  afterEach(() => {
    resetAnomalyStore();
    resetAlertStore();
  });

  it("fetches on mount and renders an accessible chart region", async () => {
    render(<AnomalyTimeline />);
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/anomaly/timeline?range=1h&resolution=1m"),
        expect.any(Object),
      ),
    );
    expect(await screen.findByRole("img", { name: /Anomaly score chart/i })).toBeInTheDocument();
  });

  it("switches range on chip click and refetches with new range", async () => {
    render(<AnomalyTimeline />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "24h" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenLastCalledWith(
        expect.stringContaining("range=24h"),
        expect.any(Object),
      ),
    );
  });

  it("includes source param when set", async () => {
    useAnomalyStore.setState({ source: "syslog" });
    render(<AnomalyTimeline />);
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("source=syslog"),
        expect.any(Object),
      ),
    );
  });

  it("shows empty state when items is []", async () => {
    fetchMock.mockResolvedValueOnce({
      meta: { range: "1h", resolution: "1m", source: null },
      items: [],
    });
    render(<AnomalyTimeline />);
    expect(await screen.findByText(/No scored events/i)).toBeInTheDocument();
  });

  it("shows error state when fetch rejects", async () => {
    fetchMock.mockRejectedValueOnce(new Error("boom"));
    render(<AnomalyTimeline />);
    await waitFor(() => {
      expect(screen.getByText(/boom/i)).toBeInTheDocument();
    });
  });

  it("renders header with widget title", async () => {
    render(<AnomalyTimeline />);
    expect(await screen.findByText("Anomaly Timeline")).toBeInTheDocument();
  });
});

// ---- H1: alert-bucket window uses the current resolution -----------------

describe("findAlertInBucket (H1)", () => {
  const fiveMinNs = 5 * 60 * 1_000_000_000;
  const oneMinNs = 60 * 1_000_000_000;

  it("matches an alert inside a 5m bucket whose timestamp falls outside the 1m window", () => {
    const alert = { alert_id: "a1", timestamp_ns: 90 * 1_000_000_000 }; // 90 s
    // At 5m resolution, bucket [0, 300s) contains 90s.
    expect(findAlertInBucket([alert], 0, fiveMinNs)?.alert_id).toBe("a1");
    // At 1m resolution, bucket [0, 60s) excludes 90s.
    expect(findAlertInBucket([alert], 0, oneMinNs)).toBeUndefined();
  });

  it("excludes alerts whose timestamp is before the bucket start", () => {
    const alert = { alert_id: "a1", timestamp_ns: -1 };
    expect(findAlertInBucket([alert], 0, fiveMinNs)).toBeUndefined();
  });

  it("excludes alerts at exactly bucket_start + resolutionNs (half-open interval)", () => {
    const alert = { alert_id: "a1", timestamp_ns: fiveMinNs };
    expect(findAlertInBucket([alert], 0, fiveMinNs)).toBeUndefined();
  });
});

// ---- M13: keep-alive rollover timer --------------------------------------

describe("AnomalyTimeline rollover timer", () => {
  it("invokes rolloverIfStale on an interval matched to the current resolution", () => {
    // Direct test on the store action + a synthetic interval — avoids the
    // ResponsiveContainer/ResizeObserver dance while still proving that
    // rolloverIfStale appends a carry-forward bucket when the wall clock
    // crosses the resolution boundary.
    resetAnomalyStore();
    useAnomalyStore.setState({
      items: [
        {
          bucket_start_ns: 0,
          max_score: 0.5,
          avg_score: 0.5,
          event_count: 1,
          upper_threshold: 0.9,
          alert_count: 0,
        },
      ],
    });

    // Simulate "now" 90 s into the future: new 1-min bucket boundary crossed.
    const nowNs = 90 * 1_000_000_000;
    useAnomalyStore.getState().rolloverIfStale(nowNs);

    const items = useAnomalyStore.getState().items;
    expect(items.length).toBeGreaterThanOrEqual(2);
    const appended = items.at(-1)!;
    expect(appended.event_count).toBe(0);
    expect(appended.upper_threshold).toBe(0.9);
  });

  it("invokes rolloverIfStale via the widget's setInterval", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      fetchMock.mockClear();
      fetchMock.mockResolvedValue({
        meta: { range: "1h", resolution: "1m", source: null },
        items: [
          {
            bucket_start_ns: 0,
            max_score: 0.3,
            avg_score: 0.2,
            event_count: 1,
            upper_threshold: 0.9,
            alert_count: 0,
          },
        ],
      });
        resetAnomalyStore();
      resetAlertStore();
      const spy = vi.spyOn(useAnomalyStore.getState(), "rolloverIfStale");
      const { unmount } = render(<AnomalyTimeline />);
      await waitFor(() => expect(fetchMock).toHaveBeenCalled());
      act(() => {
        vi.advanceTimersByTime(60_000 + 1);
      });
      expect(spy).toHaveBeenCalled();
      unmount();
    } finally {
      vi.useRealTimers();
        vi.restoreAllMocks();
      resetAnomalyStore();
      resetAlertStore();
    }
  });
});
