import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { useAlertStore, selectVisible, selectCounts, type AlertsState } from "@/stores/alerts";
import { AlertRow } from "./AlertRow";
import { AlertDetailPanel } from "./AlertDetailPanel";
import { FilterBar } from "./FilterBar";
import { SummaryBadges } from "./SummaryBadges";
import { useWebSocket } from "@/hooks/useWebSocket";
import { api, ApiError } from "@/lib/api";
import type { AlertFilter, WsFilter, WsMessage, SeverityBucket } from "@/lib/types";
import { logger } from "@/lib/logger";

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

function useStoreSlice<T>(selector: (s: AlertsState) => T): T {
  return useSyncExternalStore(
    (cb) => useAlertStore.subscribe(cb),
    () => selector(useAlertStore.getState()),
  );
}

export function AlertFeed(): JSX.Element {
  const alerts = useStoreSlice(s => s.alerts);
  const filter = useStoreSlice(s => s.filter);
  const status = useStoreSlice(s => s.status);
  const { prepend, backfill, setFilter, setStatus, setFeedback } = useAlertStore.getState();
  const [openId, setOpenId] = useState<string | null>(null);
  const [wsUrl] = useState(() => {
    const base = (import.meta.env.VITE_API_BASE as string | undefined) ?? window.location.origin;
    return base.replace(/^http/, "ws") + "/api/v1/ws";
  });

  useEffect(() => {
    let cancelled = false;
    api.get<{ items: Parameters<typeof backfill>[0] }>("/api/v1/alerts?limit=50")
      .then(r => { if (!cancelled) backfill(r.items); })
      .catch((e: ApiError) => logger.warn("warm-up failed", e));
    return () => { cancelled = true; };
  }, [backfill]);

  const onMessage = (m: WsMessage): void => {
    if (m.type === "alert") prepend(m.data);
    else if (m.type === "batch") m.events.forEach(prepend);
  };

  const { send } = useWebSocket(wsUrl, {
    onMessage,
    onStatusChange: setStatus,
    getFilterMessage: () => toWsFilter(useAlertStore.getState().filter),
  });

  useEffect(() => { send(toWsFilter(filter)); }, [filter, send]);

  const counts = useMemo(() => selectCounts(useAlertStore.getState()), [alerts, filter]);
  const visible = useMemo(() => selectVisible(useAlertStore.getState()), [alerts, filter]);
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
        {status === "closed" && <div role="status" aria-live="polite" className="bg-amber-500/10 px-3 py-1 text-xs text-amber-700">Live stream disconnected — retrying…</div>}
        <div className="flex-1 overflow-y-auto">
          {visible.length === 0 ? (
            <div className="p-8 text-center text-muted-foreground">No alerts in the last hour.</div>
          ) : (
            visible.map(a => <AlertRow key={a.alert_id} alert={a} isOpen={openId === a.alert_id} onClick={id => setOpenId(openId === id ? null : id)} />)
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
