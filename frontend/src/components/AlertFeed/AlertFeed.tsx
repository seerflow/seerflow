import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAlertStore, selectVisibleAndCounts } from "@/stores/alerts";
import { useAnomalyStore } from "@/stores/anomaly";
import { AlertRow } from "./AlertRow";
import { AlertDetailPanel } from "./AlertDetailPanel";
import { FilterBar } from "./FilterBar";
import { SummaryBadges } from "./SummaryBadges";
import { useWebSocket } from "@/hooks/useWebSocket";
import { api, ApiError } from "@/lib/api";
import type { AlertFilter, WsFilter, WsMessage, SeverityBucket, Alert, LiveEvent } from "@/lib/types";
import { logger } from "@/lib/logger";
import { useEventStore } from "@/stores/events";
import { setIntent as setWsIntent } from "@/lib/wsFilter";

const BUCKET_TO_MIN_SEV: Record<SeverityBucket, number> = { critical: 17, high: 13, medium: 9, low: 1 };

function toWsFilter(f: AlertFilter): WsFilter {
  const minSev = f.severities.size
    ? Math.min(...[...f.severities].map(b => BUCKET_TO_MIN_SEV[b]))
    : undefined;
  return {
    type: "filter",
    sources: f.sources.size ? [...f.sources] : undefined,
    alert_types: f.types.size ? [...f.types] : undefined,
    min_severity: minSev,
  };
}

export function AlertFeed(): JSX.Element {
  const alerts = useAlertStore(s => s.alerts);
  const filter = useAlertStore(s => s.filter);
  const status = useAlertStore(s => s.status);
  const openId = useAlertStore(s => s.selectedAlertId);
  const backfill = useAlertStore(s => s.backfill);
  const { prepend, setFilter, setStatus, setFeedback, selectAlert, clearSelection } = useAlertStore.getState();
  const [wsUrl] = useState(() => {
    const base = (import.meta.env.VITE_API_BASE as string | undefined) ?? window.location.origin;
    const url = base.replace(/^http/, "ws") + "/api/v1/ws";
    if (url.startsWith("ws:") && window.location.protocol === "https:") {
      logger.warn("WebSocket URL is insecure (ws:) but page served over https:", url);
    }
    return url;
  });

  const wsBufferRef = useRef<WsMessage[]>([]);
  const warmedUpRef = useRef(false);

  const handleMessage = useCallback((m: WsMessage): void => {
    if (m.type === "alert") prepend(m.data);
    else if (m.type === "batch") {
      const first = m.events.length > 0 ? m.events[0] : null;
      if (first && typeof first === "object" && "event_id" in first) {
        useEventStore.getState().ingest(m.events as unknown as LiveEvent[]);
      } else if (first) {
        (m.events as Alert[]).forEach(prepend);
      }
    }
    else if (m.type === "event" && m.data !== null && typeof m.data === "object") {
      const d = m.data as unknown as {
        event_id?: string;
        timestamp_ns?: number;
        score?: number | null;
        upper_threshold?: number | null;
        source_type?: string;
      };
      if (typeof d.timestamp_ns === "number" && typeof d.score === "number" && typeof d.source_type === "string") {
        useAnomalyStore.getState().appendScore({
          timestamp_ns: d.timestamp_ns,
          score: d.score,
          upper_threshold: d.upper_threshold ?? null,
          source_type: d.source_type,
        });
      }
      if (typeof d.event_id === "string") {
        useEventStore.getState().ingest([m.data as LiveEvent]);
      }
    }
  }, [prepend]);

  useEffect(() => {
    let cancelled = false;
    const finish = (): void => {
      if (cancelled) return;
      warmedUpRef.current = true;
      for (const m of wsBufferRef.current) handleMessage(m);
      wsBufferRef.current = [];
    };
    api.get<{ items: Parameters<typeof backfill>[0] }>("/api/v1/alerts?limit=50")
      .then(r => { if (cancelled) return; backfill(r.items); finish(); })
      .catch((e: ApiError) => { logger.warn("warm-up failed", e); finish(); });
    return () => { cancelled = true; };
  }, [backfill, handleMessage]);

  const onMessage = useCallback((m: WsMessage): void => {
    if (!warmedUpRef.current) { wsBufferRef.current.push(m); return; }
    handleMessage(m);
  }, [handleMessage]);

  const { send } = useWebSocket(wsUrl, {
    onMessage,
    onStatusChange: setStatus,
    getFilterMessage: () => setWsIntent("alerts", toWsFilter(useAlertStore.getState().filter)),
  });

  useEffect(() => {
    const merged = setWsIntent("alerts", toWsFilter(filter));
    const t = setTimeout(() => send(merged), 150);
    return () => clearTimeout(t);
  }, [filter, send]);

  useEffect(() => {
    const handler = (): void => {
      const merged = setWsIntent("alerts", toWsFilter(useAlertStore.getState().filter));
      send(merged);
    };
    window.addEventListener("seerflow:wsfilter-changed", handler);
    return () => window.removeEventListener("seerflow:wsfilter-changed", handler);
  }, [send]);

  const [showDisconnected, setShowDisconnected] = useState(false);
  useEffect(() => {
    if (status === "closed") {
      const t = setTimeout(() => setShowDisconnected(true), 3000);
      return () => clearTimeout(t);
    }
    setShowDisconnected(false);
    return undefined;
  }, [status]);

  const { visible, counts } = useAlertStore(selectVisibleAndCounts);
  const sources = useMemo(
    () => [...new Set(alerts.map(a => a.source_type).filter((s): s is string => Boolean(s)))],
    [alerts],
  );
  const tactics = useMemo(() => [...new Set(alerts.flatMap(a => a.mitre_tactics))], [alerts]);
  const open = openId ? alerts.find(a => a.alert_id === openId) ?? null : null;

  return (
    <section className="flex h-[calc(100vh-8rem)] rounded border bg-card">
      <div className="flex flex-col flex-1 min-w-0">
        <SummaryBadges counts={counts} status={status} />
        <FilterBar filter={filter} sources={sources} tactics={tactics} onChange={setFilter} />
        {showDisconnected && <div role="status" aria-live="polite" className="bg-amber-500/10 px-3 py-1 text-xs text-amber-700">Live stream disconnected — retrying…</div>}
        <div className="flex-1 overflow-y-auto">
          {visible.length === 0 ? (
            <div className="p-8 text-center text-muted-foreground">No alerts in the last hour.</div>
          ) : (
            visible.map(a => <AlertRow key={a.alert_id} alert={a} isOpen={openId === a.alert_id} onClick={id => (openId === id ? clearSelection() : selectAlert(id))} />)
          )}
        </div>
      </div>
      {open && (
        <div className="w-[420px] shrink-0 overflow-y-auto">
          <AlertDetailPanel alert={open} onFeedback={setFeedback} />
        </div>
      )}
    </section>
  );
}
