import { useCallback, useEffect, useMemo, useRef } from "react";
import { useAlertStore, selectVisibleAndCounts } from "@/stores/alerts";
import { useAnomalyStore } from "@/stores/anomaly";
import { AlertRow } from "./AlertRow";
import { AlertDetailPanel } from "./AlertDetailPanel";
import { FilterBar } from "./FilterBar";
import { SummaryBadges } from "./SummaryBadges";
import { api, ApiError } from "@/lib/api";
import { AlertSchema } from "@/lib/schemas";
import type { AlertFilter, WsFilter, WsMessage, SeverityBucket } from "@/lib/types";
import { logger } from "@/lib/logger";
import { createFilterSlot } from "@/lib/wsFilter";
import * as wsBus from "@/lib/wsBus";

// One-shot WsFilter capability for this widget — the module is imported once
// per worker so `createFilterSlot("alerts")` fires exactly once. Test harnesses
// call `_resetForTests()` which clears the issued set without breaking this
// already-bound closure.
const alertsSlot = createFilterSlot("alerts");
import { useWsSend } from "@/components/WsProvider";
import { useDebouncedWsSend } from "@/hooks/useDebouncedWsSend";

// OCSF 0..6 min-severity thresholds. Must stay aligned with
// `severityBucket` in `@/lib/severity` — see file header there.
const BUCKET_TO_MIN_SEV: Record<SeverityBucket, number> = { critical: 5, high: 4, medium: 3, low: 0 };
const MAX_WS_BUFFER = 200;  // S-194: bound buffer to survive slow warm-up under high WS load

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
  const { prepend, setFilter, setStatus, selectAlert, clearSelection } = useAlertStore.getState();
  const send = useWsSend();

  const wsBufferRef = useRef<WsMessage[]>([]);
  const warmedUpRef = useRef(false);

  const handleMessage = useCallback((m: WsMessage): void => {
    if (m.type === "alert") prepend(m.data);
    else if (m.type === "alert_batch") m.alerts.forEach(prepend);
    else if (m.type === "event") {
      // S-191 T9: parseWsFrame (WS chokepoint) enforces finite `score` and
      // bigint `timestamp_ns`/`observed_ns` plus bounded `source_type` on
      // every `event` frame before dispatch. The `typeof` guards that lived
      // here are now dead code — AlertFeed only receives validated payloads.
      // AnomalyTimeline has not yet migrated to wsBus (S-062 Phase B), so we
      // still fan out into useAnomalyStore for anomaly-scored events only.
      const d = m.data;
      if (d.score !== undefined) {
        useAnomalyStore.getState().appendScore({
          timestamp_ns: d.timestamp_ns,
          score: d.score,
          upper_threshold: d.upper_threshold ?? null,
          source_type: d.source_type,
        });
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
    api.get<{ items: Parameters<typeof backfill>[0] }>("/api/v1/alerts?limit=50", {
      schema: AlertSchema,
      itemsKey: "items",
    })
      .then(r => { if (cancelled) return; backfill(r.items); finish(); })
      .catch((e: ApiError) => { logger.warn("warm-up failed", e); finish(); });
    return () => {
      cancelled = true;
      warmedUpRef.current = false;
      wsBufferRef.current = [];
    };
  }, [backfill, handleMessage]);

  useEffect(() => {
    const onAny = (m: WsMessage): void => {
      if (!warmedUpRef.current) {
        if (wsBufferRef.current.length < MAX_WS_BUFFER) wsBufferRef.current.push(m);
        else logger.warn("ws buffer full during warm-up; dropping frame", { type: m.type });
        return;
      }
      handleMessage(m);
    };
    const offs = [
      wsBus.on("alert",       onAny),
      wsBus.on("alert_batch", onAny),
      wsBus.on("event",       onAny),
      wsBus.on("__status",    (m) => setStatus(m.status)),
    ];
    return () => { for (const off of offs) off(); };
  }, [handleMessage, setStatus]);

  const debouncedSend = useDebouncedWsSend(send, 150);
  useEffect(() => {
    const merged = alertsSlot.set(toWsFilter(filter));
    debouncedSend(merged);
  }, [filter, debouncedSend]);

  const { visible, counts } = useAlertStore(selectVisibleAndCounts);
  const sources = useMemo(
    () => [...new Set(alerts.map(a => a.source_type).filter((s): s is string => Boolean(s)))],
    [alerts],
  );
  const tactics = useMemo(() => [...new Set(alerts.flatMap(a => a.mitre_tactics))], [alerts]);
  const open = openId ? alerts.find(a => a.alert_id === openId) ?? null : null;

  return (
    <section className="flex h-full min-h-0 rounded border bg-card">
      <div className="flex flex-col flex-1 min-w-0">
        <SummaryBadges counts={counts} status={status} />
        <FilterBar filter={filter} sources={sources} tactics={tactics} onChange={setFilter} />
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
          <AlertDetailPanel alert={open} />
        </div>
      )}
    </section>
  );
}
