// S-341: Sigma rules list — mockup-faithful 5-col grid container.
//
// Header + rows share `gridTemplateColumns: '12px 1fr 80px 60px 40px'`.
// The active row is highlighted via `selectedRuleId` (parent owns selection
// state; `RuleRow` only knows whether it is selected).
import type { SigmaRuleSummary } from "@/lib/types";
import { RuleRow } from "./RuleRow";

interface Props {
  rules: SigmaRuleSummary[];
  onSelect: (ruleId: string) => void;
  onToggle?: (ruleId: string, enabled: boolean) => void;
  selectedRuleId?: string | null;
}

const GRID = "12px 1fr 80px 60px 40px";
const HEADER_CELLS = ["", "rule · tactic", "hits 24h", "prec", ""];

export function RuleTable({
  rules,
  onSelect,
  onToggle,
  selectedRuleId,
}: Props): JSX.Element {
  if (rules.length === 0) {
    return (
      <div
        className="px-3 py-6 text-sm text-muted-foreground"
        data-testid="sigma-rules-empty"
      >
        No rules match the current filters.
      </div>
    );
  }
  return (
    <div data-testid="sigma-rules-table">
      <div
        data-testid="sigma-rules-table-header"
        style={{
          display: "grid",
          gridTemplateColumns: GRID,
          gap: 10,
          padding: "8px 18px",
          borderBottom: "1px solid var(--line)",
        }}
      >
        {HEADER_CELLS.map((h, i) => (
          <span
            key={i}
            className="sf-mono"
            style={{
              fontSize: 9.5,
              color: "var(--text-3)",
              letterSpacing: "0.1em",
              textTransform: "uppercase",
            }}
          >
            {h}
          </span>
        ))}
      </div>
      {rules.map((r) => (
        <RuleRow
          key={r.rule_id}
          rule={r}
          onSelect={onSelect}
          onToggle={onToggle}
          selected={r.rule_id === selectedRuleId}
        />
      ))}
    </div>
  );
}
