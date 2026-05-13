import { useEffect, useRef } from "react";

import { api } from "@/lib/api";
import { logger } from "@/lib/logger";
import type { TimelineBucket, TimelineRange, TimelineResolution, TimelineResponse } from "@/lib/types";
import { useAnomalyStore } from "@/stores/anomaly";

export interface UseAnomalyTimelineResult {
  items: TimelineBucket[];
  loading: boolean;
  error: string | null;
  range: TimelineRange;
  resolution: TimelineResolution;
  source: string | null;
}

export function useAnomalyTimeline(): UseAnomalyTimelineResult {
  const range = useAnomalyStore((s) => s.range);
  const resolution = useAnomalyStore((s) => s.resolution);
  const source = useAnomalyStore((s) => s.source);
  const items = useAnomalyStore((s) => s.items);
  const loading = useAnomalyStore((s) => s.loading);
  const error = useAnomalyStore((s) => s.error);
  const { replaceSeries, setLoading, setError, setAlertCountTruncated } = useAnomalyStore.getState();
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    abortRef.current?.abort();
    abortRef.current = ctrl;
    setLoading(true);
    setError(null);
    const params = new URLSearchParams({ range, resolution });
    if (source) params.set("source", source);
    api
      .get<TimelineResponse>(`/api/v1/anomaly/timeline?${params.toString()}`, { signal: ctrl.signal })
      .then((res) => {
        if (ctrl.signal.aborted) return;
        replaceSeries(res.items);
        setAlertCountTruncated(res.meta.alert_count_truncated ?? false);
      })
      .catch((e: unknown) => {
        if (ctrl.signal.aborted) return;
        logger.warn("anomaly timeline fetch failed", e);
        setError("Failed to load anomaly timeline. Retrying on next change.");
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false);
      });
    return () => ctrl.abort();
  }, [range, resolution, source, replaceSeries, setLoading, setError, setAlertCountTruncated]);

  return { items, loading, error, range, resolution, source };
}
