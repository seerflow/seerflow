// S-341: Sigma rule list row — mockup-faithful 5-col grid row.
//
// Layout (from `docs/new_image/Dashboard - Sigma Rules.html`):
//
//   gridTemplateColumns: '12px 1fr 80px 60px 40px'  gap: 10
//   ┌────┬──────────────────────────┬─────────┬──────┬────┐
//   │ ●  │ rule_id                  │ hits 24h│ prec │ ›  │
//   │    │ technique · tactic       │ (right) │(right)    │
//   └────┴──────────────────────────┴─────────┴──────┴────┘
//
// The status dot (col 1) replaces the in-row toggle switch (the panel-level
// Disable button covers single-rule toggling). The chevron (col 5) signals
// drill-into.
//
// Precision is derived client-side as `1 - alert_count_24h / match_count_lifetime`
// because the wire model has no native `precision` field. When lifetime is 0
// the precision is treated as 0 (and rendered with the warn color).
import type { SigmaRuleSummary } from "@/lib/types";

interface Props {
  rule: SigmaRuleSummary;
  onSelect: (ruleId: string) => void;
  /**
   * S-341: retained for back-compat with prior callers; the row no longer
   * renders a toggle switch. Bulk toggling is reintroduced in a follow-up.
   */
  onToggle?: (ruleId: string, enabled: boolean) => void;
  selected?: boolean;
}

const GRID = "12px 1fr 80px 60px 40px";

function precisionColor(ratio: number): string {
  if (ratio > 0.8) return "var(--accent)";
  if (ratio > 0.6) return "var(--text-2)";
  return "var(--warn)";
}

function precisionRatio(rule: SigmaRuleSummary): number {
  if (rule.match_count_lifetime <= 0) return 0;
  // alerts_24h is a rough false-positive proxy against lifetime matches —
  // higher alerts vs lifetime → noisier rule → lower precision.
  const ratio = 1 - rule.alert_count_24h / rule.match_count_lifetime;
  return Math.max(0, Math.min(1, ratio));
}

export function RuleRow({ rule, onSelect, selected = false }: Props): JSX.Element {
  const handleRowClick = () => onSelect(rule.rule_id);
  const technique = rule.attack_techniques[0];
  const tactic = rule.attack_tactics[0];
  const hits = rule.alert_count_24h;
  const hitsHigh = hits > 100;
  const prec = precisionRatio(rule);

  return (
    <div
      role="row"
      data-testid={`sigma-rule-row-${rule.rule_id}`}
      data-selected={selected ? "true" : "false"}
      onClick={handleRowClick}
      style={{
        display: "grid",
        gridTemplateColumns: GRID,
        gap: 10,
        padding: "10px 18px",
        paddingLeft: 16,
        borderBottom: "1px solid var(--line)",
        alignItems: "center",
        cursor: "pointer",
        background: selected
          ? "color-mix(in oklch, var(--accent) 8%, transparent)"
          : "transparent",
        borderLeft: selected
          ? "2px solid var(--accent)"
          : "2px solid transparent",
      }}
    >
      <span
        data-testid="sigma-row-dot"
        style={{
          width: 6,
          height: 6,
          background: rule.enabled ? "var(--accent)" : "var(--text-3)",
          display: "inline-block",
        }}
      />
      <div style={{ minWidth: 0 }}>
        <div
          className="sf-mono"
          style={{
            fontSize: 12,
            color: "var(--text)",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {rule.rule_id}
        </div>
        {(technique || tactic) && (
          <div
            style={{
              fontSize: 10.5,
              color: "var(--text-3)",
              marginTop: 2,
              display: "flex",
              gap: 8,
            }}
          >
            {technique && (
              <span
                style={{
                  color: "var(--accent)",
                  fontFamily: "var(--font-mono)",
                }}
              >
                {technique.toUpperCase()}
              </span>
            )}
            {tactic && <span>· {tactic}</span>}
          </div>
        )}
      </div>
      <span
        data-testid="sigma-row-hits"
        className="sf-mono sf-tnum"
        style={{
          fontSize: 11.5,
          color: hitsHigh ? "var(--warn)" : "var(--text-2)",
          textAlign: "right",
        }}
      >
        {hits.toLocaleString()}
      </span>
      <span
        data-testid="sigma-row-prec"
        className="sf-mono sf-tnum"
        style={{
          fontSize: 11.5,
          color: precisionColor(prec),
          textAlign: "right",
        }}
      >
        {prec.toFixed(2)}
      </span>
      <span
        data-testid="sigma-row-chevron"
        style={{ fontSize: 13, color: "var(--text-3)", textAlign: "right" }}
      >
        ›
      </span>
    </div>
  );
}
