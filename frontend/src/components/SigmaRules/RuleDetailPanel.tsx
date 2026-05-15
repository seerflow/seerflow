// S-151: Side panel showing full rule details (Monaco YAML viewer + ATT&CK).
// S-154 (T8): mounts a 24h hourly-firing sparkline next to the 24h alert
// metric. Sparkline failures (network/schema) are silenced — the rest of
// the panel still renders so a flaky timeline endpoint can't break the
// detail view.
import { useEffect, useState } from "react";

import { getSigmaRule, getSigmaRuleTimeline } from "@/lib/sigmaRulesApi";
import type { SigmaRuleDetail, SigmaRuleTimelineResponse } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

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

export function RuleDetailPanel({ ruleId, onClose }: Props): JSX.Element {
  const [rule, setRule] = useState<SigmaRuleDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<SigmaRuleTimelineResponse | null>(null);

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
      <aside className="w-[480px] shrink-0 border-l p-4 text-sm text-destructive">
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
      <aside className="w-[480px] shrink-0 border-l p-4 text-sm text-muted-foreground">
        Loading rule…
      </aside>
    );
  }

  return (
    <aside className="w-[480px] shrink-0 border-l overflow-y-auto p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-base font-semibold">{rule.title}</h2>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close detail panel">
          Close
        </Button>
      </div>

      <p className="mb-4 text-sm text-muted-foreground">
        {rule.description || "No description."}
      </p>

      <dl className="mb-3 space-y-1 text-xs">
        <div className="flex justify-between gap-2">
          <dt className="text-muted-foreground">Severity</dt>
          <dd>
            <Badge variant="outline">{severityLabel(rule.severity)}</Badge>
          </dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted-foreground">Logsource</dt>
          <dd className="font-mono">
            {rule.logsource_key.filter(Boolean).join(" / ") || "—"}
          </dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted-foreground">Source</dt>
          <dd className="font-mono">{rule.source}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted-foreground">Lifetime matches</dt>
          <dd className="font-mono tabular-nums">{rule.match_count_lifetime}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted-foreground">24h alerts</dt>
          <dd className="flex items-center gap-2 font-mono tabular-nums">
            <span>{rule.alert_count_24h}</span>
            {timeline ? (
              <span className="text-muted-foreground" data-testid="rule-sparkline">
                <RuleSparkline buckets={timeline.buckets} />
              </span>
            ) : null}
          </dd>
        </div>
      </dl>

      {rule.attack_techniques.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-1">
          {rule.attack_techniques.map((t) => {
            const url = attackUrl(t);
            return url ? (
              <a
                key={t}
                className="text-xs underline"
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

      <div className="rounded border">
        <MonacoYamlEditor
          value={rule.yaml_source}
          readOnly
          height="320px"
        />
      </div>
    </aside>
  );
}
