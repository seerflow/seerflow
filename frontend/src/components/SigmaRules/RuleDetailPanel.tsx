// S-151 / S-324 / S-327 / S-341: Sigma rule detail panel.
//
// S-341 reconciles the panel chrome to
// `docs/new_image/Dashboard - Sigma Rules.html`:
//   AC5 — single inline header row: rule_id (mono 20px) + technique badge +
//         tactic + spacer + Disable / Edit YAML / Test on history.
//   AC5 — 6-stat row (hits 24h · precision · false pos · last fired · author
//         · updated) with mockup mono-uppercase labels.
//   AC6 — sticky YAML header above the Monaco editor (`${rule_id}.yml` +
//         `N lines · Copy YAML`) — copy uses `navigator.clipboard.writeText`.
//   AC7 — `Hits · last 24h` + peak label + BarHistogram driven by the
//         already-loaded 24h timeline buckets.
//
// S-327 functional bits preserved verbatim:
//   AC1 — OKLCH Monaco theme wiring (via `MonacoYamlEditor`).
//   AC3 — Edit YAML toggle with local draft + Cancel.
//   AC4 — Test on history → 24h hit count + lifetime matches.
//   Abort-on-rule-switch (S-230) for both detail + timeline fetches.
//
// The visible Close button is dropped per the mockup; Escape closes the panel.
import { useEffect, useState } from "react";

import { getSigmaRule, getSigmaRuleTimeline, toggleSigmaRule } from "@/lib/sigmaRulesApi";
import type { SigmaRuleDetail, SigmaRuleTimelineResponse } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { BarHistogram } from "@/viz/BarHistogram";
import type { BarHistogramDataPoint } from "@/viz/BarHistogram";

import { MonacoYamlEditor } from "./MonacoYamlEditor";

// MITRE technique IDs follow T#### or T####.### (sub-technique). Reject
// anything else to prevent ``javascript:`` URI injection through the
// ``href`` attribute — the rule YAML upload path is operator-trusted but
// not human-vetted before render. Returns ``null`` for invalid inputs so
// the component renders a non-clickable label instead.
const TECHNIQUE_RE = /^[Tt]\d{4}(\.\d{3})?$/;

function attackUrl(technique: string): string | null {
  if (!TECHNIQUE_RE.test(technique)) return null;
  const id = technique.toUpperCase().replace(".", "/");
  return `https://attack.mitre.org/techniques/${id}/`;
}

interface Props {
  ruleId: string;
  onClose: () => void;
}

// S-327 (AC4): a "Test on history" run summarises how often the rule has
// fired against recorded event history. With no dedicated backend endpoint
// today, we derive the count client-side from the already-loaded 24h
// timeline buckets and the rule's lifetime match count.
interface TestResult {
  hits24h: number | null;
  lifetime: number;
}

function sumBucketCounts(timeline: SigmaRuleTimelineResponse | null): number | null {
  if (!timeline) return null;
  return timeline.buckets.reduce((acc, b) => acc + b.count, 0);
}

// S-341 AC7: derive the peak bucket label ("peak N / hr at HH:MM") from the
// 24h timeline. Returns null when the timeline is empty.
function peakLabel(timeline: SigmaRuleTimelineResponse | null): string | null {
  if (!timeline || timeline.buckets.length === 0) return null;
  let bestIdx = 0;
  let best = -1;
  for (let i = 0; i < timeline.buckets.length; i++) {
    if (timeline.buckets[i].count > best) {
      best = timeline.buckets[i].count;
      bestIdx = i;
    }
  }
  if (best <= 0) return null;
  const tsMs = Number(timeline.buckets[bestIdx].bucket_start_ns) / 1e6;
  const d = new Date(tsMs);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `peak ${best} / hr at ${hh}:${mm}`;
}

// S-341 AC6: best-effort clipboard copy; never throws. A rejection (browser
// permission denial, missing API) is silently swallowed.
function copyToClipboard(text: string): void {
  try {
    const clip = navigator.clipboard;
    if (!clip) return;
    void clip.writeText(text).catch(() => {});
  } catch {
    // ignore
  }
}

export function RuleDetailPanel({ ruleId, onClose }: Props): JSX.Element {
  const [rule, setRule] = useState<SigmaRuleDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<SigmaRuleTimelineResponse | null>(null);
  const [toggling, setToggling] = useState(false);
  // S-327 (AC3): YAML edit mode. `editing` flips the Monaco editor out of
  // read-only; `draft` holds the unsaved edit buffer (Cancel discards it).
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  // S-327 (AC4): result of the most recent "Test on history" run.
  const [testResult, setTestResult] = useState<TestResult | null>(null);

  // S-230 / SEE-241: one AbortController shared by both fetches (rule
  // detail + 24h timeline). A fast ruleId switch runs this effect's
  // cleanup, aborting the prior controller so stale detail/timeline
  // responses cannot land. An aborted fetch never resolves its `.then`,
  // so the stale-setState-after-switch path is closed by the abort
  // itself — no separate `alive` flag needed. AbortError is swallowed
  // (a deliberate cancel is not an error). The timeline stays an
  // independent request so a slow/erroring timeline cannot block the
  // YAML view; its failures (AbortError included) fall back to "no
  // trend rendered".
  useEffect(() => {
    const controller = new AbortController();
    setRule(null);
    setError(null);
    setTimeline(null);
    // S-327: a rule switch discards any in-progress edit / test result.
    setEditing(false);
    setDraft("");
    setTestResult(null);
    void getSigmaRule(ruleId, controller.signal)
      .then(setRule)
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === "AbortError") return;
        if (e instanceof Error && e.name === "AbortError") return;
        setError(e instanceof Error ? e.message : String(e));
      });
    void getSigmaRuleTimeline(ruleId, controller.signal)
      .then(setTimeline)
      .catch(() => {
        // Silent: an aborted or failed timeline simply hides the trend.
      });
    return () => controller.abort();
  }, [ruleId]);

  // S-341: Escape replaces the dropped Close button.
  function handleKeyDown(e: React.KeyboardEvent): void {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    }
  }

  if (error) {
    return (
      <aside
        className="w-full h-full border-l p-4 text-sm text-destructive"
        tabIndex={-1}
        onKeyDown={handleKeyDown}
      >
        Failed to load rule: {error}
        <div className="mt-3">
          <Button size="sm" variant="ghost" onClick={onClose}>
            Close
          </Button>
        </div>
      </aside>
    );
  }

  if (!rule) {
    return (
      <aside
        className="w-full h-full border-l p-4 text-sm text-muted-foreground"
        tabIndex={-1}
        onKeyDown={handleKeyDown}
      >
        Loading rule…
      </aside>
    );
  }

  // Build BarHistogram data from timeline buckets.
  const histData: BarHistogramDataPoint[] = timeline
    ? timeline.buckets.map((b) => ({ t: Number(b.bucket_start_ns), v: b.count }))
    : [];

  // First ATT&CK technique + tactic for header.
  const primaryTechnique = rule.attack_techniques[0] ?? null;
  const primaryTactic = rule.attack_tactics[0] ?? null;

  // Source YAML (live draft when editing, persisted source otherwise).
  const yamlValue = editing ? draft : rule.yaml_source;
  const lineCount = yamlValue.split("\n").length;
  const filename = `${rule.rule_id}.yml`;

  // 6-stat values. `false_pos`, `author`, `updated` aren't in the wire model
  // today — we render `—` for those (the mockup labels still anchor the layout).
  const stats: Array<[string, string]> = [
    ["hits 24h", rule.alert_count_24h.toLocaleString()],
    [
      "precision",
      rule.match_count_lifetime > 0
        ? Math.max(
            0,
            Math.min(1, 1 - rule.alert_count_24h / rule.match_count_lifetime),
          ).toFixed(2)
        : "—",
    ],
    ["false pos", "—"],
    [
      "last fired",
      rule.last_fired_ns
        ? new Date(Number(rule.last_fired_ns) / 1e6).toLocaleDateString()
        : "—",
    ],
    ["author", rule.source ?? "—"],
    ["updated", "—"],
  ];

  // Optimistic disable toggle handler.
  async function handleDisable() {
    if (!rule || toggling) return;
    setToggling(true);
    try {
      await toggleSigmaRule(rule.rule_id, !rule.enabled);
      setRule({ ...rule, enabled: !rule.enabled });
    } finally {
      setToggling(false);
    }
  }

  // S-327 (AC3): enter edit mode, seeding the draft from the saved YAML.
  function startEditing() {
    if (!rule) return;
    setDraft(rule.yaml_source);
    setEditing(true);
  }

  // S-327 (AC3): leave edit mode, discarding the draft.
  function cancelEditing() {
    setEditing(false);
    setDraft("");
  }

  // S-327 (AC4): client-side "test against history" — count firings in the
  // loaded 24h timeline and surface them alongside the lifetime match count.
  function runTest() {
    if (!rule) return;
    setTestResult({ hits24h: sumBucketCounts(timeline), lifetime: rule.match_count_lifetime });
  }

  return (
    <aside
      data-testid="rule-detail-panel-inner"
      tabIndex={-1}
      onKeyDown={handleKeyDown}
      className="flex flex-col h-full border-l overflow-hidden"
      style={{ outline: "none" }}
    >
      {/* S-341 AC5: inline header row */}
      <div
        data-testid="rule-detail-panel-header"
        style={{
          padding: "20px 28px 18px",
          borderBottom: "1px solid var(--line)",
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
          <span
            className="sf-mono"
            style={{
              fontSize: 20,
              fontWeight: 600,
              letterSpacing: "-0.01em",
              color: "var(--text)",
            }}
          >
            {rule.rule_id}
          </span>
          {primaryTechnique && (() => {
            const href = attackUrl(primaryTechnique);
            const label = primaryTechnique.toUpperCase();
            const badge = (
              <span
                className="sf-mono"
                style={{
                  fontSize: 11,
                  color: "var(--accent)",
                  border:
                    "1px solid color-mix(in oklch, var(--accent) 30%, transparent)",
                  padding: "1px 6px",
                }}
              >
                {label}
              </span>
            );
            return href ? (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                style={{ textDecoration: "none" }}
                aria-label={`MITRE ATT&CK technique ${label}`}
              >
                {badge}
              </a>
            ) : (
              badge
            );
          })()}
          {primaryTactic && (
            <span
              className="sf-mono"
              style={{ fontSize: 11, color: "var(--text-3)" }}
            >
              {primaryTactic}
            </span>
          )}
          <span style={{ flex: 1 }} />
          <button
            onClick={() => void handleDisable()}
            disabled={toggling}
            style={{
              background: "transparent",
              border: "1px solid var(--line-2)",
              color: "var(--text-2)",
              padding: "5px 10px",
              fontSize: 11.5,
              fontFamily: "inherit",
              cursor: "pointer",
            }}
          >
            {rule.enabled ? "Disable" : "Enable"}
          </button>
          {editing ? (
            <button
              onClick={cancelEditing}
              style={{
                background: "transparent",
                border: "1px solid var(--line-2)",
                color: "var(--text)",
                padding: "5px 10px",
                fontSize: 11.5,
                fontFamily: "inherit",
                cursor: "pointer",
              }}
            >
              Cancel
            </button>
          ) : (
            <button
              onClick={startEditing}
              style={{
                background: "transparent",
                border: "1px solid var(--line-2)",
                color: "var(--text)",
                padding: "5px 10px",
                fontSize: 11.5,
                fontFamily: "inherit",
                cursor: "pointer",
              }}
            >
              Edit YAML
            </button>
          )}
          <button
            onClick={runTest}
            data-variant="accent-fill"
            style={{
              background: "var(--accent)",
              border: 0,
              color: "var(--accent-ink)",
              padding: "5px 10px",
              fontSize: 11.5,
              fontFamily: "inherit",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Test on history
          </button>
        </div>

        {/* Description */}
        {rule.description && (
          <div
            style={{
              fontSize: 13.5,
              color: "var(--text-2)",
              marginTop: 8,
              maxWidth: 640,
              lineHeight: 1.5,
            }}
          >
            {rule.description}
          </div>
        )}

        {/* S-327 (AC4): test-on-history result summary */}
        {testResult && (
          <div
            data-testid="sigma-test-result"
            style={{
              marginTop: 8,
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              color: "var(--text-2)",
            }}
          >
            {testResult.hits24h === null ? (
              <span>
                No recent history — {testResult.lifetime} lifetime matches
              </span>
            ) : (
              <span>
                {testResult.hits24h} hits in the last 24h · {testResult.lifetime}{" "}
                lifetime matches
              </span>
            )}
          </div>
        )}

        {/* S-341 AC5: 6-stat row */}
        <div
          data-testid="rule-detail-stats"
          style={{ display: "flex", gap: 28, marginTop: 18, flexWrap: "wrap" }}
        >
          {stats.map(([k, v]) => (
            <div key={k}>
              <div
                className="sf-mono"
                style={{
                  fontSize: 9.5,
                  color: "var(--text-3)",
                  letterSpacing: "0.1em",
                  textTransform: "uppercase",
                }}
              >
                {k}
              </div>
              <div
                className="sf-mono sf-tnum"
                style={{ fontSize: 13, color: "var(--text)", marginTop: 3 }}
              >
                {v}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* YAML + hit-trend */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr",
          gridTemplateRows: "1fr auto",
          flex: 1,
          overflow: "hidden",
        }}
      >
        {/* YAML pane with sticky header (AC6) — S-344: stretch to fill the
            grid row instead of capping Monaco at 360px. */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr",
            gridTemplateRows: "auto 1fr",
            background: "var(--surface)",
            borderBottom: "1px solid var(--line)",
            overflow: "hidden",
            minHeight: 0,
          }}
        >
          <div
            data-testid="sigma-yaml-header"
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "8px 16px",
              borderBottom: "1px solid var(--line)",
              background: "var(--surface)",
            }}
          >
            <span
              className="sf-mono"
              style={{
                fontSize: 10.5,
                color: "var(--text-3)",
                textTransform: "uppercase",
                letterSpacing: "0.08em",
              }}
            >
              {filename}
            </span>
            <span
              className="sf-mono"
              style={{
                fontSize: 10.5,
                color: "var(--text-3)",
                display: "flex",
                alignItems: "center",
                gap: 8,
              }}
            >
              <span>{lineCount} lines</span>
              <span aria-hidden="true">·</span>
              <button
                type="button"
                aria-label="Copy YAML"
                onClick={() => copyToClipboard(yamlValue)}
                style={{
                  background: "transparent",
                  border: 0,
                  color: "var(--text-3)",
                  fontFamily: "inherit",
                  fontSize: 10.5,
                  padding: 0,
                  cursor: "pointer",
                }}
              >
                copy ⏤
              </button>
            </span>
          </div>

          {/* Monaco fills the remaining 1fr row of the YAML grid (S-344). */}
          <div style={{ minHeight: 0, overflow: "hidden" }}>
            <MonacoYamlEditor
              value={yamlValue}
              onChange={setDraft}
              readOnly={!editing}
              height="100%"
            />
          </div>

          {/* ATT&CK techniques list (kept below the editor as supplementary
              context — the mockup focuses on a single technique up-top but
              dropping the full list would lose information for chained
              techniques). */}
          {rule.attack_techniques.length > 1 && (
            <AttackTechniqueList techniques={rule.attack_techniques} />
          )}
        </div>

        {/* S-341 AC7: hit trend */}
        <HitTrend data={histData} peak={peakLabel(timeline)} />
      </div>
    </aside>
  );
}

function AttackTechniqueList({ techniques }: { techniques: string[] }): JSX.Element {
  return (
    <div style={{ padding: "12px 16px", display: "flex", flexWrap: "wrap", gap: 6 }}>
      {techniques.map((t) => {
        const url = attackUrl(t);
        return url ? (
          <a
            key={t}
            className="text-xs underline text-accent"
            href={url}
            target="_blank"
            rel="noopener noreferrer"
          >
            {t.toUpperCase()}
          </a>
        ) : (
          <span key={t} className="text-xs text-muted-foreground">
            {t.toUpperCase()}
          </span>
        );
      })}
    </div>
  );
}

function HitTrend({
  data,
  peak,
}: {
  data: BarHistogramDataPoint[];
  peak: string | null;
}): JSX.Element {
  return (
    <div
      data-testid="sigma-hit-trend"
      style={{ padding: "14px 28px 16px" }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: 8,
        }}
      >
        <span style={{ fontSize: 13, fontWeight: 600 }}>Hits · last 24h</span>
        <span
          data-testid="sigma-hit-trend-peak"
          className="sf-mono"
          style={{ fontSize: 11, color: "var(--text-3)" }}
        >
          {peak ?? "no recent hits"}
        </span>
      </div>
      {data.length > 0 ? (
        <BarHistogram data={data} height={64} showTooltip />
      ) : (
        <div
          className="sf-mono"
          style={{ fontSize: 11, color: "var(--text-3)" }}
        >
          no timeline available
        </div>
      )}
    </div>
  );
}
