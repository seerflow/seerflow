import { create, type StoreApi } from "zustand";
import { severityBucket } from "@/lib/severity";
import type { Alert, AlertDetail, AlertFilter, SeverityBucket, WsStatus, Feedback } from "@/lib/types";

export const MAX_ALERTS = 500;

export interface AlertsState {
  alerts: Alert[];
  detail: Record<string, AlertDetail>;
  filter: AlertFilter;
  status: WsStatus;
  dropped: number;
  prepend: (a: Alert) => void;
  backfill: (a: Alert[]) => void;
  setFilter: (p: Partial<AlertFilter>) => void;
  setStatus: (s: WsStatus) => void;
  setDetail: (id: string, d: AlertDetail) => void;
  setFeedback: (id: string, f: Feedback) => void;
}

const emptyFilter = (): AlertFilter => ({
  severities: new Set(), types: new Set(), sources: new Set(), tactics: new Set(),
});

function mergePrepend(buf: Alert[], incoming: Alert, max: number): { alerts: Alert[]; dropped: number } {
  const i = buf.findIndex(x => x.alert_id === incoming.alert_id);
  let next: Alert[];
  if (i >= 0) {
    const existing = buf[i];
    const merged: Alert = incoming.timestamp_ns >= existing.timestamp_ns
      ? { ...existing, ...incoming, dedup_count: Math.max(existing.dedup_count, incoming.dedup_count) }
      : { ...incoming, ...existing, dedup_count: Math.max(existing.dedup_count, incoming.dedup_count) };
    next = [merged, ...buf.slice(0, i), ...buf.slice(i + 1)];
  } else {
    next = [incoming, ...buf];
  }
  const dropped = Math.max(0, next.length - max);
  return { alerts: next.slice(0, max), dropped };
}

export function createAlertStore(max = MAX_ALERTS): StoreApi<AlertsState> {
  return create<AlertsState>((set) => ({
    alerts: [],
    detail: {},
    filter: emptyFilter(),
    status: "connecting",
    dropped: 0,
    prepend: (a) => set(s => {
      const r = mergePrepend(s.alerts, a, max);
      return { alerts: r.alerts, dropped: s.dropped + r.dropped };
    }),
    backfill: (list) => set(s => {
      const sorted = [...list].sort((x, y) => y.timestamp_ns - x.timestamp_ns);
      let { alerts, dropped } = s;
      for (const a of sorted.slice().reverse()) {
        const r = mergePrepend(alerts, a, max);
        alerts = r.alerts; dropped += r.dropped;
      }
      return { alerts, dropped };
    }),
    setFilter: (p) => set(s => ({ filter: { ...s.filter, ...p } })),
    setStatus: (status) => set({ status }),
    setDetail: (id, d) => set(s => ({ detail: { ...s.detail, [id]: d } })),
    setFeedback: (id, feedback) => set(s => ({
      alerts: s.alerts.map(x => x.alert_id === id ? { ...x, feedback } : x),
    })),
  }));
}

export const useAlertStore = createAlertStore();

export function selectVisible(s: AlertsState): Alert[] {
  const { severities, types, sources, tactics } = s.filter;
  return s.alerts.filter(a => {
    if (severities.size && !severities.has(severityBucket(a.severity) as SeverityBucket)) return false;
    if (types.size && !types.has(a.alert_type)) return false;
    if (sources.size && a.source_type && !sources.has(a.source_type)) return false;
    if (tactics.size && !a.mitre_tactics.some(t => tactics.has(t))) return false;
    return true;
  });
}

export function selectCounts(s: AlertsState): { total: number; critical: number; high: number; medium: number; low: number } {
  const out = { total: 0, critical: 0, high: 0, medium: 0, low: 0 };
  for (const a of selectVisible(s)) {
    out.total++;
    out[severityBucket(a.severity)]++;
  }
  return out;
}
