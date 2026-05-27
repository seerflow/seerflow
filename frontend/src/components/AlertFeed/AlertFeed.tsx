import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAlertStore, selectVisibleAndCounts } from "@/stores/alerts";
import { useAnomalyStore } from "@/stores/anomaly";
import { AlertRow, ALERT_GRID } from "./AlertRow";
import { AlertsTabs, type AlertTab } from "./AlertsTabs";
import { AlertsPaginationFooter, type RowsPerPage } from "./AlertsPaginationFooter";
import { AlertVolumeStrip } from "./AlertVolumeStrip";
import { SummaryStat, TBtn, AlertsFilterChip } from "./AlertConsoleParts";
import { KPI, deriveStatus, tabCounts } from "./alertDemo";
import { api, ApiError } from "@/lib/api";
import { AlertSchema } from "@/lib/schemas";
import type { Alert, AlertFilter, WsFilter, WsMessage, SeverityBucket } from "@/lib/types";
import { logger } from "@/lib/logger";
import { createFilterSlot } from "@/lib/wsFilter";
import * as wsBus from "@/lib/wsBus";
import { serializeHash } from "@/lib/routes";

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
  const filter = useAlertStore(s => s.filter);
  const backfill = useAlertStore(s => s.backfill);
  const { prepend, setStatus } = useAlertStore.getState();
  const send = useWsSend();

  const wsBufferRef = useRef<WsMessage[]>([]);
  const warmedUpRef = useRef(false);

  const handleMessage = useCallback((m: WsMessage): void => {
    if (m.type === "alert") prepend(m.data);
    else if (m.type === "alert_batch") m.alerts.forEach(prepend);
    else if (m.type === "event") {
      // S-191 T9: parseWsFrame (WS chokepoint) enforces finite `score` and
      // bigint `timestamp_ns`/`observed_ns` plus bounded `source_type` on
      // every `event` frame before dispatch. AnomalyTimeline has not yet
      // migrated to wsBus (S-062 Phase B), so we still fan out into
      // useAnomalyStore for anomaly-scored events only.
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

  // Live visible set (severity/type/source/tactic filters from the store).
  const { visible } = useAlertStore(selectVisibleAndCounts);

  // SOC-console status tab + client-side pagination state (S-336).
  const [tab, setTab] = useState<AlertTab>("open");
  const [rowsPerPage, setRowsPerPage] = useState<RowsPerPage>(25);
  const [page, setPage] = useState(1);

  const counts = useMemo(() => tabCounts(visible), [visible]);

  // Status-tab narrows the visible set by derived workflow status (demo-fallback).
  const tabbed = useMemo<Alert[]>(() => {
    if (tab === "all") return visible;
    return visible.filter(a => deriveStatus(a) === tab);
  }, [visible, tab]);

  // Clamp the page whenever the set or page size shrinks below the current page.
  useEffect(() => { setPage(1); }, [tab, rowsPerPage]);
  const pageCount = Math.max(1, Math.ceil(tabbed.length / rowsPerPage));
  const clampedPage = Math.min(page, pageCount);
  const pageStart = (clampedPage - 1) * rowsPerPage;
  const pageRows = tabbed.slice(pageStart, pageStart + rowsPerPage);

  const openAlert = useCallback((id: string): void => {
    window.location.hash = serializeHash({ route: "alerts", id });
  }, []);

  // Filter-chip display values reflect the current store filter where it maps
  // cleanly; unmapped facets show demo defaults (no backend facet yet).
  const severityChip = filter.severities.size
    ? [...filter.severities].join(" · ")
    : "crit · warn";

  return (
    // S-336: flush full-bleed flex column — the screen chrome (padding/border)
    // is gone; this section fills its grid/flex cell. `h-full min-h-0` lets the
    // row list flex-scroll without a viewport calc.
    <section className="flex flex-col h-full min-h-0 overflow-hidden rounded-none border-0 bg-transparent">
      {/* Header: title + summary KPIs + actions */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          padding: "20px 28px 18px",
          borderBottom: "1px solid var(--line)",
          flexShrink: 0,
        }}
      >
        <div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600, letterSpacing: "-0.02em" }}>Alerts</h1>
            <span className="sf-mono" style={{ fontSize: 11, color: "var(--text-3)" }}>
              last 24h · auto-refresh 5s
            </span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 18, marginTop: 8 }}>
            <SummaryStat label="open" value={String(counts.open)} tone="crit" />
            <SummaryStat label="triaging" value={String(counts.triaging)} tone="warn" />
            <SummaryStat label="resolved" value={String(counts.resolved)} tone="text-2" />
            <span style={{ width: 1, height: 22, background: "var(--line)" }} aria-hidden />
            <SummaryStat label="mttd" value={KPI.mttd} tone="text-2" />
            <SummaryStat label="mttr" value={KPI.mttr} tone="text-2" />
            <SummaryStat label="fp rate" value={KPI.fpRate} tone="text-2" />
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <TBtn>Export ndjson</TBtn>
          <TBtn>Suppression rules</TBtn>
          <TBtn primary>+ New rule</TBtn>
        </div>
      </div>

      {/* Status tabs + filter chips */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 16,
          padding: "0 28px",
          borderBottom: "1px solid var(--line)",
          flexShrink: 0,
        }}
      >
        <AlertsTabs active={tab} counts={counts} onSelect={setTab} />
        <span style={{ flex: 1 }} />
        <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 0" }}>
          <AlertsFilterChip label="severity" value={severityChip} />
          <AlertsFilterChip label="detector" value="any" />
          <AlertsFilterChip label="assignee" value="anyone" />
          <AlertsFilterChip label="time" value="24h" />
          <AlertsFilterChip label="entity" value="" placeholder="filter by entity…" />
        </div>
      </div>

      {/* Volume strip */}
      <div
        style={{
          padding: "14px 28px 10px",
          borderBottom: "1px solid var(--line)",
          display: "flex",
          alignItems: "center",
          gap: 18,
          flexShrink: 0,
        }}
      >
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 6 }}>
            <span
              className="sf-mono"
              style={{ fontSize: 10.5, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.1em" }}
            >
              alerts / 5m bucket · last 24h
            </span>
            <span className="sf-mono" style={{ fontSize: 10.5, color: "var(--text-3)" }}>
              <span style={{ color: "var(--crit)" }}>■</span> critical&nbsp;&nbsp;
              <span style={{ color: "var(--warn)" }}>■</span> warn&nbsp;&nbsp;
              <span style={{ color: "var(--text-3)" }}>■</span> info
            </span>
          </div>
          <AlertVolumeStrip />
        </div>
      </div>

      {/* Table header */}
      <div
        className="sf-mono"
        style={{
          display: "grid",
          gridTemplateColumns: ALERT_GRID,
          alignItems: "center",
          gap: 14,
          padding: "8px 28px",
          borderBottom: "1px solid var(--line)",
          fontSize: 10,
          color: "var(--text-3)",
          textTransform: "uppercase",
          letterSpacing: "0.1em",
          background: "var(--surface)",
          flexShrink: 0,
        }}
      >
        <span aria-hidden />
        <div>Sev · Score</div>
        <div>Alert</div>
        <div>Entities</div>
        <div style={{ textAlign: "right" }}>Events</div>
        <div>Status</div>
        <div>Owner</div>
        <div style={{ textAlign: "right" }}>Updated</div>
      </div>

      {/* Rows */}
      <div className="flex-1 overflow-y-auto">
        {pageRows.length === 0 ? (
          <div className="p-8 text-center" style={{ color: "var(--text-3)", fontSize: 13 }}>
            No alerts in this view.
          </div>
        ) : (
          pageRows.map((a, i) => (
            <AlertRow
              key={a.alert_id}
              alert={a}
              selected={clampedPage === 1 && i === 0}
              onOpen={openAlert}
            />
          ))
        )}
      </div>

      {/* Footer */}
      <AlertsPaginationFooter
        total={tabbed.length}
        page={clampedPage}
        rowsPerPage={rowsPerPage}
        onPageChange={setPage}
        onRowsPerPageChange={setRowsPerPage}
      />
    </section>
  );
}
