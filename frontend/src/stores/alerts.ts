import { create } from "zustand";
import { severityBucket } from "@/lib/severity";
import type { Alert, AlertDetail, AlertFilter, SeverityBucket, WsStatus, Feedback } from "@/lib/types";

export const MAX_ALERTS = 500;

export interface AlertsState {
  alerts: Alert[];
  detail: Record<string, AlertDetail>;
  filter: AlertFilter;
  status: WsStatus;
  dropped: number;
  selectedAlertId: string | null;
  prepend: (a: Alert) => void;
  backfill: (a: Alert[]) => void;
  setFilter: (p: Partial<AlertFilter>) => void;
  setStatus: (s: WsStatus) => void;
  setDetail: (id: string, d: AlertDetail) => void;
  setFeedback: (id: string, f: Feedback) => void;
  selectAlert: (id: string) => void;
  clearSelection: () => void;
}

const emptyFilter = (): AlertFilter => ({
  severities: new Set(), types: new Set(), sources: new Set(), tactics: new Set(),
});

function insertSorted(buf: Alert[], a: Alert): Alert[] {
  const pos = buf.findIndex(x => x.timestamp_ns <= a.timestamp_ns);
  return pos === -1 ? [...buf, a] : [...buf.slice(0, pos), a, ...buf.slice(pos)];
}

function mergePrepend(buf: Alert[], incoming: Alert, max: number): { alerts: Alert[]; dropped: number } {
  const i = buf.findIndex(x => x.alert_id === incoming.alert_id);
  let next: Alert[];
  if (i >= 0) {
    const existing = buf[i];
    const merged: Alert = incoming.timestamp_ns >= existing.timestamp_ns
      ? { ...existing, ...incoming, dedup_count: Math.max(existing.dedup_count, incoming.dedup_count) }
      : { ...incoming, ...existing, dedup_count: Math.max(existing.dedup_count, incoming.dedup_count) };
    const without = [...buf.slice(0, i), ...buf.slice(i + 1)];
    next = insertSorted(without, merged);
  } else {
    next = insertSorted(buf, incoming);
  }
  const dropped = Math.max(0, next.length - max);
  return { alerts: next.slice(0, max), dropped };
}

export function createAlertStore(max = MAX_ALERTS) {
  return create<AlertsState>((set) => ({
    alerts: [],
    detail: {},
    filter: emptyFilter(),
    status: "connecting",
    dropped: 0,
    selectedAlertId: null,
    prepend: (a) => set(s => {
      const r = mergePrepend(s.alerts, a, max);
      return { alerts: r.alerts, dropped: s.dropped + r.dropped };
    }),
    backfill: (list) => set(s => {
      const byId = new Map<string, Alert>();
      for (const a of s.alerts) byId.set(a.alert_id, a);
      for (const a of list) {
        const existing = byId.get(a.alert_id);
        if (!existing) {
          byId.set(a.alert_id, a);
        } else if (a.timestamp_ns >= existing.timestamp_ns) {
          byId.set(a.alert_id, { ...existing, ...a, dedup_count: Math.max(existing.dedup_count, a.dedup_count) });
        } else {
          byId.set(a.alert_id, { ...a, ...existing, dedup_count: Math.max(existing.dedup_count, a.dedup_count) });
        }
      }
      const sorted = [...byId.values()].sort((x, y) =>
        y.timestamp_ns === x.timestamp_ns ? 0 : y.timestamp_ns > x.timestamp_ns ? 1 : -1,
      );
      const dropped = Math.max(0, sorted.length - max);
      return { alerts: sorted.slice(0, max), dropped: s.dropped + dropped };
    }),
    setFilter: (p) => set(s => ({ filter: { ...s.filter, ...p } })),
    setStatus: (status) => set({ status }),
    setDetail: (id, d) => set(s => ({ detail: { ...s.detail, [id]: d } })),
    setFeedback: (id, feedback) => set(s => ({
      alerts: s.alerts.map(x => x.alert_id === id ? { ...x, feedback } : x),
    })),
    selectAlert: (id) => set({ selectedAlertId: id }),
    clearSelection: () => set({ selectedAlertId: null }),
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

// S-194 AC-5: single-pass selector returning {visible, counts}. Memoised by
// (alerts, filter) reference identity so zustand's strict equality keeps the
// subscription stable across renders that don't change either source.
let _vcCacheKey: { alerts: Alert[]; filter: AlertFilter } | null = null;
let _vcCacheVal: { visible: Alert[]; counts: ReturnType<typeof selectCounts> } | null = null;

export function selectVisibleAndCounts(s: AlertsState): { visible: Alert[]; counts: ReturnType<typeof selectCounts> } {
  if (_vcCacheKey && _vcCacheKey.alerts === s.alerts && _vcCacheKey.filter === s.filter && _vcCacheVal) {
    return _vcCacheVal;
  }
  const visible = selectVisible(s);
  const counts = { total: 0, critical: 0, high: 0, medium: 0, low: 0 };
  for (const v of visible) { counts.total++; counts[severityBucket(v.severity)]++; }
  _vcCacheKey = { alerts: s.alerts, filter: s.filter };
  _vcCacheVal = { visible, counts };
  return _vcCacheVal;
}
