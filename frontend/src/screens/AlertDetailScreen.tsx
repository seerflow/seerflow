import React, { useCallback, useEffect, useRef, useState } from "react";
import { parseHash } from "@/lib/routes";
import { useAlertStore } from "@/stores/alerts";
import { api, ApiError } from "@/lib/api";
import { fetchAlertExplanation } from "@/lib/liveStats";
import { AlertDetailSchema } from "@/lib/schemas";
import { severityBucket, SEVERITY_LABEL } from "@/lib/severity";
import { formatRelative } from "@/lib/relativeTime";
import { SFBadge } from "@/components/ui/primitives/Badge";
import { SideBlock } from "@/components/ui/primitives/SideBlock";
import { RiskBar } from "@/components/ui/primitives/RiskBar";
import { MonoLabel } from "@/components/ui/primitives/MonoLabel";
import { EntityGlyph } from "@/components/ui/primitives/EntityGlyph";
import { Button } from "@/components/ui/button";
import { KillChain, KILL_CHAIN_STAGES } from "@/components/AlertDetail/KillChain";
import { AiExplanation } from "@/components/AlertDetail/AiExplanation";
import { cn } from "@/lib/utils";
import type { Alert, AlertDetail } from "@/lib/types";
import type { EntityType } from "@/components/ui/primitives/EntityGlyph";
import type { SFBadgeVariant } from "@/components/ui/primitives/Badge";

// ── Severity → SFBadge variant map ───────────────────────────────────────────
const SEVERITY_BADGE: Record<string, SFBadgeVariant> = {
  critical: "crit",
  high: "warn",
  medium: "accent",
  low: "mute",
};

// ── Kill-chain active stage derivation ───────────────────────────────────────
/**
 * Map MITRE ATT&CK tactic IDs from the alert to the 7-stage kill-chain index.
 * Returns the highest matched index (most advanced stage the alert has reached).
 */
function deriveKillChainActiveIdx(mitreTactics: string[]): number | undefined {
  const tacticSet = new Set(mitreTactics.map((t) => t.toUpperCase()));
  let lastMatch: number | undefined;
  KILL_CHAIN_STAGES.forEach((stage, idx) => {
    if (tacticSet.has(stage.taId.toUpperCase())) {
      lastMatch = idx;
    }
  });
  return lastMatch;
}

// ── Entity type normalizer ────────────────────────────────────────────────────
const ENTITY_GLYPH_TYPES: Set<EntityType> = new Set(["user", "host", "ip", "service", "process"]);

function toGlyphType(entityType: string | null): EntityType {
  const t = entityType?.toLowerCase() ?? "";
  return ENTITY_GLYPH_TYPES.has(t as EntityType) ? (t as EntityType) : "host";
}

// ── Correlated events list ────────────────────────────────────────────────────
interface CorrelatedEventsProps {
  events: Array<{ event_id: string; timestamp_ns: bigint; message: string }>;
}

function CorrelatedEvents({ events }: CorrelatedEventsProps): JSX.Element {
  const [autoScroll, setAutoScroll] = useState(true);
  const listRef = useRef<HTMLUListElement>(null);

  useEffect(() => {
    if (autoScroll && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [events, autoScroll]);

  if (events.length === 0) {
    return (
      <p className="text-xs text-text-3 italic px-1">No correlated events.</p>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between">
        <MonoLabel className="text-[10px]">Correlated events ({events.length})</MonoLabel>
        <label className="flex items-center gap-1 text-[10px] text-text-3 cursor-pointer">
          <input
            type="checkbox"
            aria-label="auto-scroll"
            checked={autoScroll}
            onChange={(e) => setAutoScroll(e.target.checked)}
            className="h-3 w-3"
          />
          auto-scroll
        </label>
      </div>
      <ul
        ref={listRef}
        className="max-h-40 overflow-y-auto flex flex-col gap-px border border-line"
        aria-label="correlated events"
      >
        {events.map((ev) => {
          const ts = new Date(
            Number(ev.timestamp_ns / 1_000_000n),
          ).toISOString().slice(11, 23);
          return (
            <li
              key={ev.event_id}
              className="flex items-baseline gap-2 px-2 py-1 hover:bg-surface-2"
            >
              <span className="sf-mono text-[10px] text-text-3 flex-shrink-0">{ts}</span>
              <span className="text-xs text-text-2 truncate">{ev.message}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// ── Main AlertDetailScreen ────────────────────────────────────────────────────

/**
 * Alert detail screen — S-321.
 *
 * Reads the alert ID from the URL hash (#/alerts/:id), looks up the alert in
 * the store (populated by AlertFeed warm-up), or fetches the detail directly
 * if navigating straight to the route. Renders:
 *   - Header: severity badge, score, tactic count, first-seen, action buttons
 *   - KillChain timeline (7 stages)
 *   - Correlated events list with auto-scroll toggle
 *   - Right rail: Entities, MITRE ATT&CK, AI Explanation SideBlocks
 */
export const AlertDetailScreen: React.FC = () => {
  const alertId = parseHash(window.location.hash).id ?? null;
  const storeAlert: Alert | null = useAlertStore(
    (s) => (alertId ? (s.alerts.find((a) => a.alert_id === alertId) ?? null) : null),
  );
  const [detail, setDetail] = useState<AlertDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(true);
  const [acknowledged, setAcknowledged] = useState(false);
  // S-328 AC4: LLM-explain narrative; null until/unless the endpoint responds.
  const [llmNarrative, setLlmNarrative] = useState<string | null>(null);

  // Fetch the full detail (which also contains the base alert fields).
  // If the alert isn't in the store yet (e.g., direct URL navigation), the
  // detail response is used as the Alert source as well.
  useEffect(() => {
    if (!alertId) return;
    let cancelled = false;
    setLoadingDetail(true);
    setDetail(null);
    api
      .get<AlertDetail>(`/api/v1/alerts/${alertId}`, { schema: AlertDetailSchema })
      .then((d) => {
        if (!cancelled) {
          setDetail(d);
          setLoadingDetail(false);
          // Backfill the store so kill-chain and entity info are available even
          // on direct URL navigation (store may be empty before AlertFeed warms up).
          useAlertStore.getState().backfill([d]);
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          const msg = e instanceof ApiError ? e.message : "Failed to load detail";
          // eslint-disable-next-line no-console
          console.warn("[AlertDetailScreen] detail fetch failed:", msg);
          setLoadingDetail(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [alertId]);

  // S-328 AC4: pull the LLM explanation from the dedicated endpoint when
  // available. On any failure (route absent, error, abort) the helper returns
  // null — no throw, no console error — and the demo narrative is used instead.
  useEffect(() => {
    if (!alertId) return;
    const ctrl = new AbortController();
    setLlmNarrative(null);
    void fetchAlertExplanation(alertId, ctrl.signal).then((text) => {
      if (!ctrl.signal.aborted && text) setLlmNarrative(text);
    });
    return () => ctrl.abort();
  }, [alertId]);

  // Use store alert (from backfill or warm-up) or fall back to detail payload.
  const alert: Alert | null = storeAlert ?? (detail as Alert | null);

  const handleBack = useCallback(() => {
    window.location.hash = "#/alerts";
  }, []);

  const handleAcknowledge = useCallback(() => {
    setAcknowledged(true);
  }, []);

  // ── Loading (direct URL navigation — waiting for API detail fetch) ──────────
  if (!alertId) {
    return (
      <div
        data-testid="alert-detail-not-found"
        className="flex flex-col items-center justify-center h-full gap-4"
      >
        <p className="text-text-3">Alert not found.</p>
        <Button variant="outline" size="sm" onClick={handleBack}>
          Back to Alerts
        </Button>
      </div>
    );
  }

  if (loadingDetail && !alert) {
    return (
      <div
        data-testid="alert-detail-screen"
        className="flex flex-col items-center justify-center h-full gap-4"
      >
        <p className="text-text-3">Loading…</p>
      </div>
    );
  }

  // ── Not-found (load complete but API returned nothing) ────────────────────
  if (!alert) {
    return (
      <div
        data-testid="alert-detail-not-found"
        className="flex flex-col items-center justify-center h-full gap-4"
      >
        <p className="text-text-3">Alert not found.</p>
        <Button variant="outline" size="sm" onClick={handleBack}>
          Back to Alerts
        </Button>
      </div>
    );
  }

  // ── Derived values ────────────────────────────────────────────────────────
  const bucket = severityBucket(alert.severity);
  const badgeVariant = SEVERITY_BADGE[bucket] ?? "mute";
  const firstSeen = formatRelative(alert.timestamp_ns);
  const tacticCount = alert.mitre_tactics.length;
  const killChainActiveIdx = deriveKillChainActiveIdx(alert.mitre_tactics);
  const killChainStages = KILL_CHAIN_STAGES.map((_, idx) => ({
    relativeTime: idx === killChainActiveIdx ? firstSeen : undefined,
  }));

  const correlated = detail?.contributing_events ?? [];

  return (
    <div
      data-testid="alert-detail-screen"
      className="flex h-full min-h-0 overflow-hidden"
    >
      {/* ── Main content ────────────────────────────────────────────────── */}
      <div className="flex flex-1 flex-col min-w-0 overflow-y-auto">

        {/* Header */}
        <header className="flex items-start gap-3 border-b border-line px-4 py-3">
          <div className="flex flex-col gap-2 flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <SFBadge variant={badgeVariant}>{SEVERITY_LABEL[bucket]}</SFBadge>
              <span className="sf-mono text-xs text-text-3">
                score {alert.risk_score.toFixed(2)}
              </span>
              {tacticCount > 0 && (
                <span className="sf-mono text-[10px] text-text-3">
                  {tacticCount} tactic{tacticCount !== 1 ? "s" : ""}
                </span>
              )}
              <span className="sf-mono text-[10px] text-text-3">
                {firstSeen}
              </span>
            </div>
            <h1 className="text-base font-semibold text-text truncate">
              {alert.rule_name}
            </h1>
            <p className="text-xs text-text-3 italic">Kill-chain progression</p>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <Button
              size="sm"
              variant={acknowledged ? "default" : "outline"}
              onClick={handleAcknowledge}
              aria-label={acknowledged ? "acknowledged" : "acknowledge"}
            >
              {acknowledged ? "Acknowledged" : "Acknowledge"}
            </Button>
            <Button size="sm" variant="outline" aria-label="run playbook">
              Run playbook
            </Button>
          </div>
        </header>

        {/* Kill-chain + correlated events */}
        <div className="flex flex-col gap-4 px-4 py-4">
          <KillChain activeIdx={killChainActiveIdx} stages={killChainStages} />
          <CorrelatedEvents events={correlated} />
        </div>
      </div>

      {/* ── Right rail ──────────────────────────────────────────────────── */}
      <aside
        className={cn(
          "w-[300px] shrink-0 border-l border-line flex flex-col overflow-y-auto",
          "bg-surface",
        )}
        aria-label="alert detail right rail"
      >
        {/* Entities */}
        <SideBlock title="Entities">
          {alert.entity_type && alert.entity_value ? (
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-2">
                <EntityGlyph type={toGlyphType(alert.entity_type)} size={20} />
                <span className="sf-mono text-xs truncate">{alert.entity_value}</span>
              </div>
              <RiskBar value={alert.risk_score} />
              <span className="sf-mono text-[10px] text-text-3">
                risk {(alert.risk_score * 100).toFixed(0)}%
              </span>
            </div>
          ) : (
            <span className="text-xs text-text-3 italic">No entities.</span>
          )}
        </SideBlock>

        {/* MITRE ATT&CK */}
        <SideBlock title="MITRE ATT&CK">
          {alert.mitre_techniques.length > 0 ? (
            <div className="flex flex-wrap gap-1">
              {alert.mitre_techniques.map((t) => (
                <span
                  key={t}
                  className={cn(
                    "sf-mono border border-line px-[5px] py-[1px] text-[10px] leading-none",
                    "text-info bg-[color-mix(in_oklch,var(--info)_8%,transparent)]",
                    "border-[color-mix(in_oklch,var(--info)_30%,transparent)]",
                  )}
                >
                  {t}
                </span>
              ))}
            </div>
          ) : (
            <span className="text-xs text-text-3 italic">No techniques mapped.</span>
          )}
        </SideBlock>

        {/* AI Explanation */}
        <SideBlock title="AI Explanation">
          <AiExplanation
            narrative={
              loadingDetail
                ? ""
                : (llmNarrative ?? detail?.message ?? alert.message)
            }
            provenance={alert.mitre_techniques}
            loading={loadingDetail}
          />
        </SideBlock>
      </aside>
    </div>
  );
};
