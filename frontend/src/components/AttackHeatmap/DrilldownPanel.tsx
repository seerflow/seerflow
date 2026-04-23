import { useEffect, useMemo, useRef, useState } from "react";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { api } from "@/lib/api";
import { useDrilldownStore } from "@/stores/drilldown";
import { useAlertStore } from "@/stores/alerts";
import { useLayoutStore } from "@/stores/layout";
import { severityIcon } from "@/lib/severityIcon";
import { formatRelative } from "@/lib/relativeTime";
import type { Alert } from "@/lib/types";
import type { MergedTactic } from "./types";

function fmtDate(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

interface DrilldownPanelProps {
  matrix: MergedTactic[];
  coverageWindow: { since: string; until: string };
}

interface FetchState {
  loading: boolean;
  error: string | null;
  alerts: Alert[];
}

const INITIAL: FetchState = { loading: false, error: null, alerts: [] };
const CACHE_MAX = 50;

function statusLabel(c: boolean, d: boolean): "Detected" | "Covered" | "Gap" {
  if (c && d) return "Detected";
  if (c) return "Covered";
  return "Gap";
}

function buildAlertsUrl(tactic: string, technique: string, since: string, until: string): string {
  const p = new URLSearchParams();
  p.set("tactic", tactic);
  p.set("technique", technique);
  p.set("limit", "20");
  p.set("since", since);
  p.set("until", until);
  return `/api/v1/alerts?${p.toString()}`;
}

function cacheKey(tactic: string, technique: string, since: string, until: string): string {
  return `${tactic}|${technique}|${since}|${until}`;
}

export function DrilldownPanel({ matrix, coverageWindow: win }: DrilldownPanelProps) {
  const openCell = useDrilldownStore((s) => s.openCell);
  const close = useDrilldownStore((s) => s.close);
  const alertFeedMounted = useLayoutStore((s) => s.widgets.includes("alertFeed"));

  const [state, setState] = useState<FetchState>(INITIAL);
  const cacheRef = useRef<Map<string, Alert[]>>(new Map());
  const abortRef = useRef<AbortController | null>(null);
  const [fetchTick, setFetchTick] = useState(0);

  const cell = useMemo(() => {
    if (!openCell) return null;
    const tac = matrix.find((t) => t.shortname === openCell.tactic);
    if (!tac) return null;
    const tech = tac.techniques.find((t) => t.id === openCell.technique);
    if (!tech) return null;
    return { tac, tech };
  }, [matrix, openCell]);

  useEffect(() => {
    if (openCell !== null && cell === null) {
      close();
    }
  }, [openCell, cell, close]);

  useEffect(() => {
    if (!openCell) return;
    const key = cacheKey(openCell.tactic, openCell.technique, win.since, win.until);
    const cached = cacheRef.current.get(key);
    if (cached) {
      setState({ loading: false, error: null, alerts: cached });
      return;
    }
    abortRef.current?.abort();
    const ctl = new AbortController();
    abortRef.current = ctl;
    setState({ loading: true, error: null, alerts: [] });
    const url = buildAlertsUrl(openCell.tactic, openCell.technique, win.since, win.until);
    api
      .get<{ items: Alert[] }>(url, { signal: ctl.signal })
      .then((res) => {
        if (ctl.signal.aborted) return;
        const cache = cacheRef.current;
        if (cache.size >= CACHE_MAX) {
          const oldest = cache.keys().next().value;
          if (oldest !== undefined) cache.delete(oldest);
        }
        cache.set(key, res.items);
        setState({ loading: false, error: null, alerts: res.items });
      })
      .catch((e: unknown) => {
        if (ctl.signal.aborted) return;
        const msg = e instanceof Error ? e.message : String(e);
        setState({ loading: false, error: msg, alerts: [] });
      });
    return () => {
      ctl.abort();
    };
  }, [openCell, win.since, win.until, fetchTick]);

  function handleSelect(id: string) {
    close();
    useAlertStore.getState().selectAlert(id);
    if (typeof globalThis !== "undefined" && "location" in globalThis) {
      globalThis.location.hash = "#";
    }
  }

  function handleRetry() {
    if (!openCell) return;
    cacheRef.current.delete(cacheKey(openCell.tactic, openCell.technique, win.since, win.until));
    setFetchTick((t) => t + 1);
  }

  const isOpen = openCell !== null && cell !== null;

  return (
    <Sheet open={isOpen} onOpenChange={(o) => { if (!o) close(); }}>
      <SheetContent side="right" className="w-full sm:max-w-[480px] overflow-y-auto">
        {cell && (
          <>
            <SheetHeader>
              <SheetTitle>
                {cell.tech.id} — {cell.tech.name}
              </SheetTitle>
              <SheetDescription className="sr-only">
                Coverage details for this MITRE ATT&CK technique, including loaded rules and recent matching alerts.
              </SheetDescription>
              <p className="text-xs text-zinc-500">
                {cell.tac.name} · <span data-status>{statusLabel(cell.tech.covered, cell.tech.detected)}</span>
              </p>
              <p className="text-xs text-zinc-500">
                {cell.tech.ruleCount} rules · {cell.tech.alertCount} alerts (
                {fmtDate(win.since)} → {fmtDate(win.until)})
              </p>
            </SheetHeader>

            <section className="mt-4">
              <h3 className="mb-2 text-sm font-semibold">Rules</h3>
              {cell.tech.ruleNames.length === 0 ? (
                <p className="text-xs italic text-zinc-500">
                  No rules cover this technique.
                </p>
              ) : (
                <ul className="ml-4 list-disc space-y-1 text-sm">
                  {[...new Set(cell.tech.ruleNames)].sort().map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              )}
            </section>

            <section className="mt-6">
              <h3 className="mb-2 text-sm font-semibold">Recent alerts</h3>
              {state.loading && (
                <div role="status" className="space-y-2">
                  <div className="h-6 w-full animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
                  <div className="h-6 w-5/6 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
                  <div className="h-6 w-3/4 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
                </div>
              )}
              {state.error && !state.loading && (
                <div className="space-y-2">
                  <p className="text-xs text-red-500">{state.error}</p>
                  <button
                    type="button"
                    onClick={handleRetry}
                    className="rounded border px-2 py-1 text-xs"
                  >
                    Retry
                  </button>
                </div>
              )}
              {!state.loading && !state.error && state.alerts.length === 0 && (
                <p className="text-xs italic text-zinc-500">No alerts in window.</p>
              )}
              {!state.loading && !state.error && state.alerts.length > 0 && (
                <>
                  {!alertFeedMounted && (
                    <p className="mb-2 text-[11px] italic text-amber-600 dark:text-amber-400">
                      Add the Alert Feed widget to inspect details.
                    </p>
                  )}
                  <ul className="divide-y divide-zinc-200 dark:divide-zinc-800">
                    {state.alerts.map((a) => {
                      const ico = severityIcon(a.severity);
                      return (
                        <li key={a.alert_id}>
                          <button
                            type="button"
                            onClick={() => handleSelect(a.alert_id)}
                            className="flex w-full items-start gap-2 py-2 text-left hover:bg-zinc-50 dark:hover:bg-zinc-900/40"
                            aria-label={`Open alert ${a.alert_id} — ${a.message || a.rule_name}`}
                          >
                            <span aria-hidden className="text-base leading-tight">
                              {ico.emoji}
                            </span>
                            <span className="flex-1 text-xs">
                              <span className="block font-medium">{a.message || a.rule_name}</span>
                              <span className="text-zinc-500">
                                {a.entity_value ? `${a.entity_type ?? "entity"}:${a.entity_value} · ` : ""}
                                {formatRelative(a.timestamp_ns)}
                              </span>
                            </span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </>
              )}
            </section>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
