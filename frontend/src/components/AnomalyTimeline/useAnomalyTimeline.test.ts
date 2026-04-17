import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useAnomalyTimeline } from "./useAnomalyTimeline";
import { resetAnomalyStore, useAnomalyStore } from "@/stores/anomaly";
import type { TimelineResponse } from "@/lib/types";

const fetchMock = vi.fn<(...args: unknown[]) => Promise<TimelineResponse>>();
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
  ],
});

describe("useAnomalyTimeline", () => {
  beforeEach(() => {
    fetchMock.mockClear();
    fetchMock.mockResolvedValue(okResponse());
    resetAnomalyStore();
  });
  afterEach(() => {
    resetAnomalyStore();
  });

  it("fetches on mount with current range/resolution/source", async () => {
    renderHook(() => useAnomalyTimeline());
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/anomaly/timeline?range=1h&resolution=1m"),
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      ),
    );
  });

  it("refetches when range changes", async () => {
    const { rerender } = renderHook(() => useAnomalyTimeline());
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    useAnomalyStore.getState().setRange("24h");
    rerender();
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("range=24h"),
        expect.any(Object),
      ),
    );
  });

  it("aborts previous fetch on re-trigger", async () => {
    renderHook(() => useAnomalyTimeline());
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const firstSignal = fetchMock.mock.calls[0][1].signal as AbortSignal;
    useAnomalyStore.getState().setRange("6h");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(firstSignal.aborted).toBe(true);
  });

  it("sets error state on fetch failure", async () => {
    fetchMock.mockRejectedValueOnce(new Error("network"));
    renderHook(() => useAnomalyTimeline());
    await waitFor(() =>
      expect(useAnomalyStore.getState().error).toMatch(/Failed to load/),
    );
  });
});
