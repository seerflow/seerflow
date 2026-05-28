import React, { useCallback, useEffect, useRef, useState } from "react";
import { parseHash } from "@/lib/routes";
import { useAlertStore } from "@/stores/alerts";
import { api, ApiError } from "@/lib/api";
import { fetchAlertExplanation } from "@/lib/liveStats";
import { AlertDetailSchema } from "@/lib/schemas";
import { severityBucket, SEVERITY_LABEL } from "@/lib/severity";
import { formatRelative } from "@/lib/relativeTime";
import { SideBlock } from "@/components/ui/primitives/SideBlock";
import { EntityGlyph } from "@/components/ui/primitives/EntityGlyph";
import { Button } from "@/components/ui/button";
import { KillChain, KILL_CHAIN_STAGES } from "@/components/AlertDetail/KillChain";
import { AiExplanation } from "@/components/AlertDetail/AiExplanation";
import { getTechnique } from "@/lib/mitreTechniques";
import type { Alert, AlertDetail, CorrelatedEvent, SeverityBucket } from "@/lib/types";
import type { EntityType } from "@/components/ui/primitives/EntityGlyph";

// ── Severity bucket → semantic token (crit/warn/accent/mute) ──────────────────
const BUCKET_TOKEN: Record<SeverityBucket, string> = {
  critical: "--crit",
  high: "--warn",
  medium: "--accent",
  low: "--mute",
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

// ── Tactic-chain title ────────────────────────────────────────────────────────
const TA_ID_TO_LABEL: Record<string, string> = Object.fromEntries(
  KILL_CHAIN_STAGES.map((s) => [s.taId.toUpperCase(), s.label]),
);

/** Humanize a tactic token: known `TA00xx` → stage label; otherwise title-case. */
function humanizeTactic(raw: string): string {
  const byId = TA_ID_TO_LABEL[raw.toUpperCase()];
  if (byId) return byId;
  return raw
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^\w/, (c) => c.toUpperCase());
}

// ── Entity type normalizer ────────────────────────────────────────────────────
const ENTITY_GLYPH_TYPES: Set<EntityType> = new Set(["user", "host", "ip", "service", "process"]);

function toGlyphType(entityType: string | null): EntityType {
  const t = entityType?.toLowerCase() ?? "";
  return ENTITY_GLYPH_TYPES.has(t as EntityType) ? (t as EntityType) : "host";
}

// ── Correlated events list ────────────────────────────────────────────────────
interface CorrelatedEventsProps {
  events: CorrelatedEvent[];
}

/** HH:MM:SS.mmm from nanosecond epoch. */
function formatClock(ns: bigint): string {
  return new Date(Number(ns / 1_000_000n)).toISOString().slice(11, 23);
}

// ── S-338: severity_text → row tint bucket ───────────────────────────────────
type LevelBucket = "crit" | "warn" | null;

/**
 * Map an event's free-form `severity_text` (OCSF / OTel / vendor labels) to
 * the two tint buckets the mockup uses. Unknown / missing severities fall
 * through to `null` (no tint), matching the mockup's untinted INFO/DEBUG rows.
 */
function severityToTint(severity?: string): LevelBucket {
  if (!severity) return null;
  const s = severity.toUpperCase();
  if (s === "CRITICAL" || s === "FATAL" || s === "ERROR") return "crit";
  if (s === "WARN" || s === "WARNING") return "warn";
  return null;
}

/**
 * Render an entity-path hop as `src → dst`. Missing src/dst fall back to
 * a typography-soft dash; both missing → `null` so the caller can render
 * a placeholder.
 */
function EntityPathCell({ path }: { path: CorrelatedEvent["entity_path"] }): JSX.Element {
  const src = path?.src ?? null;
  const dst = path?.dst ?? null;
  if (!src && !dst) {
    return <span className="truncate text-text-3">—</span>;
  }
  return (
    <span className="flex min-w-0 items-baseline gap-1 truncate">
      <span className="truncate text-accent">{src ?? "—"}</span>
      <span className="text-text-3">→</span>
      <span className="truncate text-accent">{dst ?? "—"}</span>
    </span>
  );
}

/**
 * Correlated-events panel — header (count + auto-scroll toggle) + a
 * `90px 50px 200px 1fr` grid (ts · level · entity-path · message) per the
 * mockup. S-338: backend now hydrates `severity_text` + `entity_path` so the
 * level column shows the real label and rows tint when `severity_text`
 * resolves to `crit` / `warn`. Older payloads (no enrichment) fall back to a
 * tasteful dash placeholder. Auto-scroll keeps the latest row in view.
 */
function CorrelatedEvents({ events }: CorrelatedEventsProps): JSX.Element {
  const [autoScroll, setAutoScroll] = useState(true);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoScroll && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [events, autoScroll]);

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-4 border-b border-line px-7 py-3">
        <span className="text-[12.5px] font-medium text-text">Correlated events</span>
        <span className="sf-mono text-[11px] text-text-3">{events.length}</span>
        <span className="flex-1" />
        <label className="flex cursor-pointer items-center gap-1 sf-mono text-[11px] text-text-3">
          <input
            type="checkbox"
            aria-label="auto-scroll"
            checked={autoScroll}
            onChange={(e) => setAutoScroll(e.target.checked)}
            className="h-3 w-3"
          />
          auto-scroll {autoScroll ? "⏸" : "▶"}
        </label>
      </div>

      {/* Rows */}
      {events.length === 0 ? (
        <p className="px-7 py-3 text-xs italic text-text-3">No correlated events.</p>
      ) : (
        <div
          ref={listRef}
          aria-label="correlated events"
          className="flex-1 overflow-y-auto sf-mono text-[11.5px] text-text-2"
        >
          {events.map((ev) => {
            const tint = severityToTint(ev.severity_text);
            const tintToken = tint === "crit" ? "--crit" : tint === "warn" ? "--warn" : null;
            const tintStyle = tintToken
              ? { background: `color-mix(in oklch, var(${tintToken}) 8%, transparent)` }
              : undefined;
            const level = ev.severity_text?.toUpperCase() ?? "—";
            const levelClass =
              tint === "crit" ? "text-crit" : tint === "warn" ? "text-warn" : "text-text-3";
            return (
              <div
                key={ev.event_id}
                data-tint={tint ?? undefined}
                className="grid items-center gap-3 border-b border-line px-7 py-2 last:border-b-0"
                style={{ gridTemplateColumns: "90px 50px 200px 1fr", ...tintStyle }}
              >
                <span className="sf-tnum text-text-3">{formatClock(ev.timestamp_ns)}</span>
                <span className={levelClass}>{level}</span>
                <EntityPathCell path={ev.entity_path} />
                <span className="truncate text-text-2">{ev.message}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Main AlertDetailScreen ────────────────────────────────────────────────────

/**
 * Alert detail screen — S-321 (kill-chain + AI), S-328 (live LLM-explain),
 * S-337 (reconciled to the `DashAlertDetail` mockup).
 *
 * Reads the alert ID from the URL hash (#/alerts/:id), looks up the alert in
 * the store (populated by AlertFeed warm-up), or fetches the detail directly
 * on direct navigation. Layout: a flush `1fr / 360px` grid filling the
 * viewport —
 *   - Header: sev·score badge, kill_chain·N-tactics + first-seen meta,
 *     Acknowledge / Run-playbook actions, tactic-chain title, entity summary.
 *   - Kill-chain timeline section.
 *   - Correlated-events grid.
 *   - Right rail: Entities (risk bars), MITRE ATT&CK rows, AI Explanation.
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
        className="flex h-full flex-col items-center justify-center gap-4"
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
        className="flex h-full flex-col items-center justify-center gap-4"
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
        className="flex h-full flex-col items-center justify-center gap-4"
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
  const bucketColor = `var(${BUCKET_TOKEN[bucket]})`;
  const firstSeen = formatRelative(alert.timestamp_ns);
  const tacticCount = alert.mitre_tactics.length;
  const killChainActiveIdx = deriveKillChainActiveIdx(alert.mitre_tactics);
  const killChainStages = KILL_CHAIN_STAGES.map((_, idx) => ({
    relativeTime: idx === killChainActiveIdx ? firstSeen : undefined,
  }));

  // Tactic-chain title: humanized tactics joined by arrows, last stage tinted.
  // Falls back to the rule name when no tactics are mapped.
  const tacticChain = alert.mitre_tactics.map(humanizeTactic);
  const correlated = detail?.contributing_events ?? [];

  return (
    <div
      data-testid="alert-detail-screen"
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 360px",
        height: "100%",
        overflow: "hidden",
      }}
    >
      {/* ── Main column ─────────────────────────────────────────────────── */}
      <div className="flex min-w-0 flex-col overflow-hidden">
        {/* Header */}
        <header className="border-b border-line px-7 pb-[22px] pt-5">
          <div className="mb-3 flex flex-wrap items-center gap-2.5">
            {/* sev · score badge */}
            <span
              className="sf-mono inline-flex items-center gap-1.5 border px-2 py-[3px] text-[11px] tracking-[0.08em]"
              style={{
                color: bucketColor,
                borderColor: `color-mix(in oklch, ${bucketColor} 35%, transparent)`,
                background: `color-mix(in oklch, ${bucketColor} 12%, transparent)`,
              }}
            >
              <span
                aria-hidden="true"
                className="h-1.5 w-1.5"
                style={{ background: bucketColor }}
              />
              {SEVERITY_LABEL[bucket].toUpperCase()} · {alert.risk_score.toFixed(2)}
            </span>
            <span className="sf-mono text-[11px] text-text-3">
              kill_chain · {tacticCount} tactic{tacticCount !== 1 ? "s" : ""}
            </span>
            <span className="sf-mono truncate text-[11px] text-text-3" title={alert.rule_name}>
              · {alert.rule_name}
            </span>
            <span className="sf-mono text-[11px] text-text-3">· first seen {firstSeen}</span>
            <span className="flex-1" />
            <Button
              size="sm"
              variant={acknowledged ? "default" : "outline"}
              onClick={handleAcknowledge}
              aria-label={acknowledged ? "acknowledged" : "acknowledge"}
            >
              {acknowledged ? "Acknowledged" : "Acknowledge"}
            </Button>
            <Button size="sm" aria-label="run playbook">
              Run playbook ↗
            </Button>
          </div>

          {/* Tactic-chain title */}
          <h1
            className="text-[22px] font-semibold leading-[1.1] tracking-[-0.02em] text-text"
            style={{ overflow: "hidden", textOverflow: "ellipsis" }}
          >
            {tacticChain.length > 0
              ? tacticChain.map((t, i) => (
                  <React.Fragment key={`${t}-${i}`}>
                    {i > 0 && <span className="text-text-3">{" → "}</span>}
                    <span style={i === tacticChain.length - 1 ? { color: bucketColor } : undefined}>
                      {t}
                    </span>
                  </React.Fragment>
                ))
              : alert.rule_name}
          </h1>

          {/* Entity summary */}
          <div className="sf-mono mt-1.5 text-xs text-text-3">
            entity ={" "}
            <span className="text-accent">{alert.entity_value ?? "—"}</span> · {correlated.length}{" "}
            events
            {alert.mitre_techniques.length > 0 && (
              <> · {alert.mitre_techniques.length} technique{alert.mitre_techniques.length !== 1 ? "s" : ""}</>
            )}
          </div>
        </header>

        {/* Kill-chain timeline */}
        <section className="border-b border-line px-7 py-6">
          <div className="sf-mono mb-4 text-[10px] uppercase tracking-[0.12em] text-text-3">
            kill chain
          </div>
          <KillChain activeIdx={killChainActiveIdx} stages={killChainStages} />
        </section>

        {/* Correlated events */}
        <CorrelatedEvents events={correlated} />
      </div>

      {/* ── Right rail ──────────────────────────────────────────────────── */}
      <aside
        className="flex flex-col overflow-y-auto border-l border-line bg-bg"
        aria-label="alert detail right rail"
      >
        {/* Entities */}
        <SideBlock title="Entities">
          {alert.entity_type && alert.entity_value ? (
            <div className="flex flex-col gap-2.5">
              <div className="flex items-center gap-2.5">
                <EntityGlyph type={toGlyphType(alert.entity_type)} />
                <div className="min-w-0 flex-1">
                  <div className="sf-mono truncate text-xs text-accent">{alert.entity_value}</div>
                  <div className="mt-1 h-0.5 w-full bg-surface-2">
                    <div
                      className="h-full"
                      style={{
                        width: `${Math.min(100, Math.max(0, alert.risk_score * 100))}%`,
                        background: bucketColor,
                      }}
                    />
                  </div>
                </div>
                <span className="sf-mono sf-tnum text-[11px] text-text-2">
                  {alert.risk_score.toFixed(2)}
                </span>
              </div>
            </div>
          ) : (
            <span className="text-xs italic text-text-3">No entities.</span>
          )}
        </SideBlock>

        {/* MITRE ATT&CK */}
        <SideBlock title="MITRE ATT&CK">
          {alert.mitre_techniques.length > 0 ? (
            <div className="flex flex-col gap-1.5">
              {alert.mitre_techniques.map((t, i) => {
                // S-338: prefer the catalogue tactic (per-technique) over the
                // alert-level mitre_tactics positional fallback, which assumes
                // a 1:1 ordering that doesn't always hold.
                const catalogued = getTechnique(t);
                const tactic = (
                  catalogued?.tactic ??
                  (alert.mitre_tactics[i]
                    ? humanizeTactic(alert.mitre_tactics[i]).toLowerCase()
                    : "")
                ).replace(/[-_]/g, " ");
                return (
                  <div
                    key={t}
                    className="flex flex-col gap-0.5 border border-line bg-surface px-2 py-1.5"
                  >
                    <div className="flex items-baseline gap-2">
                      <span className="sf-mono text-[10.5px] tracking-[0.04em] text-accent">
                        {t}
                      </span>
                      {tactic && (
                        <span className="sf-mono ml-auto text-[9.5px] uppercase tracking-[0.06em] text-text-3">
                          {tactic}
                        </span>
                      )}
                    </div>
                    {catalogued?.name && (
                      <span className="text-[11px] leading-snug text-text-2">
                        {catalogued.name}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <span className="text-xs italic text-text-3">No techniques mapped.</span>
          )}
        </SideBlock>

        {/* AI Explanation */}
        <SideBlock title="AI Explanation">
          <AiExplanation
            narrative={loadingDetail ? "" : (llmNarrative ?? detail?.message ?? alert.message)}
            provenance={alert.mitre_techniques}
            loading={loadingDetail}
            generatedBy="sf-llm · explain"
          />
        </SideBlock>
      </aside>
    </div>
  );
};
