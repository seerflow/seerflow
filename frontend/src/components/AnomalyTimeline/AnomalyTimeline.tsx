import { useEffect, useMemo } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { RESOLUTION_NS } from "@/lib/buckets";
import { useAlertStore } from "@/stores/alerts";
import { selectKnownSources, useAnomalyStore } from "@/stores/anomaly";

import { DisconnectedBanner } from "@/components/DisconnectedBanner";
import { findAlertInBucket } from "./alertMatch";
import { SourceSelect } from "./SourceSelect";
import { TimeRangeChips } from "./TimeRangeChips";
import { useAnomalyTimeline } from "./useAnomalyTimeline";

const MAX_DOTS = 50;

function nsToMs(ns: bigint): number {
  return Number(ns / 1_000_000n);
}

export function AnomalyTimeline(): JSX.Element {
  const { items, loading, error, range, resolution, source } = useAnomalyTimeline();

  const alertCountTruncated = useAnomalyStore((s) => s.alertCountTruncated);

  // Actions via getState() — no subscription needed, stable references
  const { setRange, setSource, rolloverIfStale } = useAnomalyStore.getState();
  const knownSources = useAnomalyStore(selectKnownSources);

  // Alert store — keep separate subscriptions (different store)
  const selectAlert = useAlertStore.getState().selectAlert;
  const alerts = useAlertStore((s) => s.alerts);
  const status = useAlertStore((s) => s.status);

  const resolutionMs = useMemo(
    () => Number(RESOLUTION_NS[resolution] / 1_000_000n),
    [resolution],
  );

  useEffect(() => {
    const handle = setInterval(() => {
      // BigInt math: Date.now() * 1_000_000 overflows JS number precision
      // for far-future timestamps. Stay in bigint all the way to rolloverIfStale.
      const nowNs = BigInt(Date.now()) * 1_000_000n;
      rolloverIfStale(nowNs);
    }, resolutionMs);
    return () => clearInterval(handle);
  }, [resolutionMs, rolloverIfStale]);

  const latestThreshold = useMemo(() => {
    for (let i = items.length - 1; i >= 0; i -= 1) {
      const t = items[i].upper_threshold;
      if (t !== null) return t;
    }
    return null;
  }, [items]);

  const chartData = useMemo(
    () =>
      items.map((b) => ({
        x: nsToMs(b.bucket_start_ns),
        max_score: b.max_score,
        upper_threshold: b.upper_threshold,
        event_count: b.event_count,
        alert_count: b.alert_count,
      })),
    [items],
  );

  const alertDots = useMemo(() => {
    const withAlerts = items.filter((b) => b.alert_count > 0);
    if (withAlerts.length <= MAX_DOTS) return withAlerts;
    const step = Math.ceil(withAlerts.length / MAX_DOTS);
    return withAlerts.filter((_, i) => i % step === 0);
  }, [items]);

  const ariaLabel = useMemo(() => {
    const latest = items.at(-1);
    const s = latest?.max_score ?? "n/a";
    return `Anomaly score chart. Current score ${s}. Threshold ${latestThreshold ?? "n/a"}. Range ${range}.`;
  }, [items, latestThreshold, range]);

  return (
    <section
      aria-labelledby="anomaly-timeline-title"
      className="rounded-lg border bg-card p-3 h-[calc(100vh-8rem)]"
    >
      <header className="flex items-center justify-between gap-2 mb-2">
        <h2 id="anomaly-timeline-title" className="text-sm font-medium">
          Anomaly Timeline
        </h2>
        {alertCountTruncated && (
          <span className="text-xs text-muted-foreground">Some alert markers not shown</span>
        )}
        <div className="flex items-center gap-2">
          <SourceSelect value={source} options={knownSources} onChange={setSource} />
          <TimeRangeChips value={range} onChange={setRange} />
        </div>
      </header>
      <DisconnectedBanner status={status} />
      <div role="img" aria-label={ariaLabel} style={{ height: 320 }}>
        {loading && items.length === 0 ? (
          <div className="h-full flex items-center justify-center text-xs text-muted-foreground">
            Loading…
          </div>
        ) : error ? (
          <div className="h-full flex items-center justify-center text-xs text-destructive">
            {error}
          </div>
        ) : items.length === 0 ? (
          <div className="h-full flex items-center justify-center text-xs text-muted-foreground">
            No scored events in this range
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" className="opacity-30" />
              <XAxis
                dataKey="x"
                type="number"
                domain={["dataMin", "dataMax"]}
                tickFormatter={(v: number) => new Date(v).toLocaleTimeString()}
                tick={{ fontSize: 10 }}
              />
              <YAxis
                domain={[0, (max: number) => Math.max(max, latestThreshold ?? 0) * 1.1]}
                tick={{ fontSize: 10 }}
              />
              <Tooltip labelFormatter={(v: number) => new Date(v).toLocaleString()} />
              <Line
                type="monotone"
                dataKey="max_score"
                stroke="var(--color-chart-score)"
                dot={false}
                isAnimationActive={false}
                connectNulls={false}
              />
              <Line
                type="monotone"
                dataKey="upper_threshold"
                stroke="var(--color-chart-threshold)"
                strokeDasharray="4 2"
                dot={false}
                isAnimationActive={false}
                connectNulls
              />
              {alertDots.map((b) => {
                const resolutionNs = RESOLUTION_NS[resolution];
                const alertInBucket = findAlertInBucket(
                  alerts,
                  b.bucket_start_ns,
                  resolutionNs,
                );
                return (
                  <ReferenceDot
                    key={String(b.bucket_start_ns)}
                    x={nsToMs(b.bucket_start_ns)}
                    y={b.max_score ?? 0}
                    r={b.alert_count > 1 ? 6 : 4}
                    fill="var(--color-chart-alert)"
                    stroke="var(--color-chart-alert)"
                    onClick={() => alertInBucket && selectAlert(alertInBucket.alert_id)}
                    label={
                      b.alert_count > 1
                        ? { value: String(b.alert_count), fontSize: 9 }
                        : undefined
                    }
                  />
                );
              })}
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </section>
  );
}
