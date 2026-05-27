// S-151: Side panel showing full rule details (Monaco YAML viewer + ATT&CK).
// S-154 (T8): mounts a 24h hourly-firing sparkline next to the 24h alert metric.
// S-324: Restyled — SFBadge for technique, 6-up Stat row, BarHistogram hit trend,
//        action buttons (Disable / Edit YAML / Test on history), OKLCH Monaco theme.
import { useEffect, useState } from "react";

import { getSigmaRule, getSigmaRuleTimeline, toggleSigmaRule } from "@/lib/sigmaRulesApi";
import type { SigmaRuleDetail, SigmaRuleTimelineResponse } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { SFBadge } from "@/components/ui/primitives/Badge";
import { Stat } from "@/components/ui/primitives/Stat";
import { BarHistogram } from "@/viz/BarHistogram";
import type { BarHistogramDataPoint } from "@/viz/BarHistogram";

import { MonacoYamlEditor } from "./MonacoYamlEditor";
import { RuleSparkline } from "./RuleSparkline";
import { severityLabel } from "./severity";

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
// timeline buckets and the rule's lifetime match count. `hits24h` is null
// when the timeline never resolved (e.g. endpoint 404/error) so the UI can
// show a graceful "no recent history" fallback.
interface TestResult {
  hits24h: number | null;
  lifetime: number;
}

function sumBucketCounts(timeline: SigmaRuleTimelineResponse | null): number | null {
  if (!timeline) return null;
  return timeline.buckets.reduce((acc, b) => acc + b.count, 0);
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
  // sparkline rendered".
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
        // Silent: the metric row still shows the count without the
        // chart; an aborted timeline is silenced here too.
      });
    return () => controller.abort();
  }, [ruleId]);

  if (error) {
    return (
      <aside className="w-full h-full border-l p-4 text-sm text-destructive">
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
      <aside className="w-full h-full border-l p-4 text-sm text-muted-foreground">
        Loading rule…
      </aside>
    );
  }

  // Build BarHistogram data from timeline buckets.
  const histData: BarHistogramDataPoint[] = timeline
    ? timeline.buckets.map((b) => ({ t: Number(b.bucket_start_ns), v: b.count }))
    : [];

  // First ATT&CK technique for badge (primary).
  const primaryTechnique = rule.attack_techniques[0] ?? null;

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
      className="flex flex-col h-full border-l overflow-hidden"
      data-testid="rule-detail-panel-inner"
    >
      {/* Header */}
      <div className="shrink-0 px-4 pt-4 pb-3 border-b border-line">
        <div className="flex items-start justify-between gap-2 mb-2">
          <h2 className="text-sm font-semibold text-text leading-tight">{rule.title}</h2>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close detail panel" className="shrink-0">
            Close
          </Button>
        </div>

        {/* Rule ID + technique badge row */}
        <div className="flex items-center gap-2 mb-2">
          <span className="sf-mono text-[11px] text-text-3">{rule.rule_id}</span>
          {primaryTechnique && (
            <SFBadge variant="accent">
              {primaryTechnique.toUpperCase()}
            </SFBadge>
          )}
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => void handleDisable()}
            disabled={toggling}
            className="sf-mono text-[11px] border border-line text-text-2 px-2 py-1 leading-none hover:border-line-2 transition-colors disabled:opacity-50"
          >
            {rule.enabled ? "Disable" : "Enable"}
          </button>
          {editing ? (
            <button
              onClick={cancelEditing}
              className="sf-mono text-[11px] border border-line text-text-2 px-2 py-1 leading-none hover:border-line-2 transition-colors"
            >
              Cancel
            </button>
          ) : (
            <button
              onClick={startEditing}
              className="sf-mono text-[11px] border border-line text-text-2 px-2 py-1 leading-none hover:border-line-2 transition-colors"
            >
              Edit YAML
            </button>
          )}
          <button
            onClick={runTest}
            className="sf-mono text-[11px] border border-line text-text-2 px-2 py-1 leading-none hover:border-line-2 transition-colors"
          >
            Test on history
          </button>
        </div>

        {/* S-327 (AC4): test-on-history result summary */}
        {testResult && (
          <div
            data-testid="sigma-test-result"
            className="mt-2 sf-mono text-[11px] text-text-2"
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
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* 6-up Stat row */}
        <div className="grid grid-cols-3 gap-3">
          <Stat label="Severity" value={severityLabel(rule.severity)} />
          <Stat label="24h alerts" value={rule.alert_count_24h} />
          <Stat label="Lifetime" value={rule.match_count_lifetime} />
          <Stat label="Logsource" value={rule.logsource_key.filter(Boolean).join("/") || "—"} />
          <Stat label="Source" value={rule.source} />
          <Stat
            label="Last fired"
            value={rule.last_fired_ns ? new Date(Number(rule.last_fired_ns) / 1e6).toLocaleDateString() : "Never"}
          />
        </div>

        {/* 24h sparkline + hit-trend histogram */}
        <div>
          <div className="sf-mono text-[10px] text-text-3 uppercase tracking-[0.1em] mb-1">
            Hit trend (24h)
          </div>
          <div className="flex items-center gap-3">
            <span className="sf-tnum text-sm text-text-2">{rule.alert_count_24h}</span>
            {timeline ? (
              <span className="text-muted-foreground" data-testid="rule-sparkline">
                <RuleSparkline buckets={timeline.buckets} />
              </span>
            ) : null}
          </div>
          {histData.length > 0 && (
            <BarHistogram
              data={histData}
              height={56}
              className="mt-2"
              showTooltip
            />
          )}
        </div>

        {/* Description */}
        {rule.description && (
          <p className="text-xs text-text-2 leading-relaxed">{rule.description}</p>
        )}

        {/* ATT&CK techniques */}
        {rule.attack_techniques.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {rule.attack_techniques.map((t) => {
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
        )}

        {/* Monaco YAML view — editable when AC3 edit mode is active */}
        <div className="rounded border border-line">
          <MonacoYamlEditor
            value={editing ? draft : rule.yaml_source}
            onChange={setDraft}
            readOnly={!editing}
            height="320px"
          />
        </div>
      </div>
    </aside>
  );
}
