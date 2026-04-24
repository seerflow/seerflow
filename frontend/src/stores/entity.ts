import { create } from "zustand";
import { api, ApiError } from "@/lib/api";
import { parseEntityHash, isValidEntityUuid } from "@/lib/hash";
import { logger } from "@/lib/logger";
import type {
  EntitySearchResult,
  EntityRelation,
  EntityEvent,
  EntityTimelineResponse,
  EntityViewState,
  RiskBucket,
  RiskHistoryResponse,
  TimelineRange,
} from "@/lib/types";

const RECENT_KEY = "seerflow:recentEntities";
const RECENT_MAX = 10;
const RANGE_TO_MS: Record<TimelineRange, number> = {
  "1h": 3_600_000,
  "6h": 21_600_000,
  "24h": 86_400_000,
  "7d": 604_800_000,
};

type Loading = "idle" | "searching" | "loading-detail" | "error";

interface State {
  query: string;
  searchResults: EntitySearchResult[];
  recent: EntitySearchResult[];
  selectedEntityUuid: string | null;
  selectedEntityType: string | null;
  selectedEntityValue: string | null;
  range: TimelineRange;
  sourceFilter: string | null;
  severityMin: number | null;
  events: EntityEvent[];
  related: EntityRelation[];
  total: number;
  loading: Loading;
  error: string | null;

  riskHistory: RiskBucket[];
  riskHistoryLoading: boolean;
  riskHistoryError: string | null;

  _searchAbort: AbortController | null;
  _detailAbort: AbortController | null;
  _riskAbort: AbortController | null;
  _searchTimer: ReturnType<typeof setTimeout> | null;

  setQuery: (q: string) => void;
  runSearch: () => Promise<void>;
  selectEntity: (uuid: string) => Promise<void>;
  setRange: (r: TimelineRange) => Promise<void>;
  setSourceFilter: (s: string | null) => Promise<void>;
  setSeverityMin: (n: number | null) => Promise<void>;
  refresh: () => Promise<void>;
  fetchRiskHistory: () => Promise<void>;
  restoreFromHash: (hash: string) => Promise<void>;
  clearSelection: () => void;
  pushRecent: (r: EntitySearchResult) => void;
  clearRecent: () => void;
}

function isRecentEntry(x: unknown): x is EntitySearchResult {
  if (x === null || typeof x !== "object") return false;
  const r = x as Record<string, unknown>;
  return (
    isValidEntityUuid(r.entity_uuid) &&
    typeof r.entity_value === "string" &&
    typeof r.entity_type === "string"
  );
}

function loadRecent(): EntitySearchResult[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    // Validate every entry so tampered / stale storage never feeds untrusted
    // UUIDs into navigateToEntity.
    return parsed.filter(isRecentEntry).slice(0, RECENT_MAX);
  } catch (e) {
    logger.warn("Failed to load recent entities", e);
    localStorage.removeItem(RECENT_KEY);
    return [];
  }
}

function persistRecent(items: EntitySearchResult[]): void {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(items.slice(0, RECENT_MAX)));
  } catch (e) {
    logger.warn("Failed to persist recent entities", e);
  }
}

export const useEntityStore = create<State>((set, get) => ({
  query: "",
  searchResults: [],
  recent: loadRecent(),
  selectedEntityUuid: null,
  selectedEntityType: null,
  selectedEntityValue: null,
  range: "24h" as TimelineRange,
  sourceFilter: null,
  severityMin: null,
  events: [],
  related: [],
  total: 0,
  loading: "idle" as Loading,
  error: null,

  riskHistory: [],
  riskHistoryLoading: false,
  riskHistoryError: null,

  _searchAbort: null,
  _detailAbort: null,
  _riskAbort: null,
  _searchTimer: null,

  setQuery: (q) => set({ query: q }),

  runSearch: async () => {
    const { query, _searchAbort } = get();
    if (_searchAbort) _searchAbort.abort();
    if (!query.trim()) {
      set({ searchResults: [], loading: "idle", error: null, _searchAbort: null });
      return;
    }
    const ctl = new AbortController();
    set({ loading: "searching", error: null, _searchAbort: ctl });
    try {
      const results = await api.get<EntitySearchResult[]>(
        `/api/v1/entities/search?q=${encodeURIComponent(query.slice(0, 256))}`,
        { signal: ctl.signal },
      );
      if (ctl.signal.aborted) return;
      set({ searchResults: results, loading: "idle", _searchAbort: null });
    } catch (e) {
      if (ctl.signal.aborted) return;
      const msg = e instanceof ApiError && e.status === 429
        ? "Search throttled — try again in a moment"
        : e instanceof Error ? e.message : "Search failed";
      set({ error: msg, loading: "error", _searchAbort: null });
    }
  },

  selectEntity: async (uuid) => {
    const { searchResults, recent } = get();
    const found =
      searchResults.find((r) => r.entity_uuid === uuid) ??
      recent.find((r) => r.entity_uuid === uuid) ??
      null;
    set({
      selectedEntityUuid: uuid,
      selectedEntityType: found ? String(found.entity_type) : null,
      selectedEntityValue: found ? found.entity_value : null,
    });
    await get().refresh();
    void get().fetchRiskHistory();
  },

  setRange: async (r) => {
    set({ range: r });
    if (get().selectedEntityUuid) {
      await get().refresh();
      void get().fetchRiskHistory();
    }
  },

  setSourceFilter: async (s) => {
    set({ sourceFilter: s });
    if (get().selectedEntityUuid) await get().refresh();
  },

  setSeverityMin: async (n) => {
    set({ severityMin: n });
    if (get().selectedEntityUuid) await get().refresh();
  },

  fetchRiskHistory: async () => {
    const { selectedEntityUuid: uuid, range, _riskAbort } = get();
    if (!uuid) return;
    _riskAbort?.abort();
    const ctrl = new AbortController();
    set({ _riskAbort: ctrl, riskHistoryLoading: true, riskHistoryError: null, riskHistory: [] });
    try {
      const res = await api.get<RiskHistoryResponse>(
        `/api/v1/entities/${uuid}/risk-history?range=${encodeURIComponent(range)}`,
        { signal: ctrl.signal },
      );
      if (ctrl.signal.aborted) return;
      set({ riskHistory: res.items, riskHistoryLoading: false, _riskAbort: null });
    } catch (e) {
      if (ctrl.signal.aborted) return;
      const msg = e instanceof ApiError ? e.message : e instanceof Error ? e.message : "fetch failed";
      logger.warn("risk-history fetch failed", e);
      set({ riskHistoryError: msg, riskHistoryLoading: false, _riskAbort: null });
    }
  },

  refresh: async () => {
    const { selectedEntityUuid, range, sourceFilter, severityMin, _detailAbort } = get();
    if (!selectedEntityUuid) return;
    if (_detailAbort) _detailAbort.abort();
    const nowNs = BigInt(Date.now()) * 1_000_000n;
    const startNs = nowNs - BigInt(RANGE_TO_MS[range]) * 1_000_000n;
    const params = new URLSearchParams({
      start_ns: startNs.toString(),
      end_ns: nowNs.toString(),
      limit: "1000",
    });
    if (sourceFilter) params.set("source_type", sourceFilter);
    if (severityMin != null) params.set("severity_min", String(severityMin));
    const ctl = new AbortController();
    set({ loading: "loading-detail", error: null, _detailAbort: ctl });
    try {
      const resp = await api.get<EntityTimelineResponse>(
        `/api/v1/entities/${selectedEntityUuid}/timeline?${params.toString()}`,
        { signal: ctl.signal },
      );
      if (ctl.signal.aborted) return;
      set({
        events: resp.events,
        related: resp.related,
        total: resp.total,
        loading: "idle",
        _detailAbort: null,
      });
    } catch (e) {
      if (ctl.signal.aborted) return;
      set({
        error: e instanceof Error ? e.message : "Timeline fetch failed",
        loading: "error",
        _detailAbort: null,
      });
    }
  },

  restoreFromHash: async (hash) => {
    const parsed = parseEntityHash(hash);
    if (!parsed) {
      set({ selectedEntityUuid: null, selectedEntityType: null, selectedEntityValue: null });
      return;
    }
    const { searchResults, recent } = get();
    const found =
      searchResults.find((r) => r.entity_uuid === parsed.entity_uuid) ??
      recent.find((r) => r.entity_uuid === parsed.entity_uuid) ??
      null;
    set({
      selectedEntityUuid: parsed.entity_uuid,
      selectedEntityType: found ? String(found.entity_type) : null,
      selectedEntityValue: found ? found.entity_value : null,
      range: parsed.range,
      sourceFilter: parsed.source ?? null,
      severityMin: parsed.severity_min ?? null,
    });
    await get().refresh();
    void get().fetchRiskHistory();
  },

  clearSelection: () => {
    get()._riskAbort?.abort();
    set({
      selectedEntityUuid: null,
      selectedEntityType: null,
      selectedEntityValue: null,
      events: [],
      related: [],
      total: 0,
      sourceFilter: null,
      severityMin: null,
      riskHistory: [],
      riskHistoryLoading: false,
      riskHistoryError: null,
      _riskAbort: null,
    });
  },

  pushRecent: (r) => {
    const filtered = get().recent.filter((x) => x.entity_uuid !== r.entity_uuid);
    const next = [r, ...filtered].slice(0, RECENT_MAX);
    set({ recent: next });
    persistRecent(next);
  },

  clearRecent: () => {
    set({ recent: [] });
    localStorage.removeItem(RECENT_KEY);
  },
}));

export function currentViewState(): EntityViewState | null {
  const { selectedEntityUuid, range, sourceFilter, severityMin } = useEntityStore.getState();
  if (!selectedEntityUuid) return null;
  return {
    entity_uuid: selectedEntityUuid,
    range,
    source: sourceFilter ?? undefined,
    severity_min: severityMin ?? undefined,
  };
}
