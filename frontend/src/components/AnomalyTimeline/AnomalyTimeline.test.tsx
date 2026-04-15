import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AnomalyTimeline } from "./AnomalyTimeline";
import type { TimelineResponse } from "@/lib/types";

const fetchMock = vi.fn();
vi.mock("@/lib/api", () => ({
  api: {
    get: (...args: unknown[]) => fetchMock(...args),
    post: vi.fn(),
  },
  ApiError: class ApiError extends Error {},
}));

// Recharts requires a non-zero parent size. ResponsiveContainer uses ResizeObserver.
class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}

const okResponse = (): TimelineResponse => ({
  meta: { range: "1h", resolution: "1m", source: null },
  items: [
    { bucket_start_ns: 0, max_score: 0.3, avg_score: 0.2, event_count: 2, upper_threshold: 0.9, alert_count: 0 },
    { bucket_start_ns: 60_000_000_000, max_score: 0.7, avg_score: 0.5, event_count: 3, upper_threshold: 0.9, alert_count: 1 },
  ],
});

describe("AnomalyTimeline", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockResolvedValue(okResponse());
    vi.stubGlobal("ResizeObserver", RO);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
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
    const mod = await import("@/stores/anomaly");
    mod.useAnomalyStore.setState({ source: "syslog" });
    render(<AnomalyTimeline />);
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("source=syslog"),
        expect.any(Object),
      ),
    );
    mod.useAnomalyStore.setState({ source: null });
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
