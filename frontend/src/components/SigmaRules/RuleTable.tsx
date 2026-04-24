// S-151: Sigma rules table — wraps RuleRow children with header.
import type { SigmaRuleSummary } from "@/lib/types";
import { RuleRow } from "./RuleRow";

interface Props {
  rules: SigmaRuleSummary[];
  onSelect: (ruleId: string) => void;
  onToggle: (ruleId: string, enabled: boolean) => void;
}

export function RuleTable({ rules, onSelect, onToggle }: Props): JSX.Element {
  if (rules.length === 0) {
    return (
      <div className="px-3 py-6 text-sm text-muted-foreground" data-testid="sigma-rules-empty">
        No rules match the current filters.
      </div>
    );
  }
  return (
    <table className="min-w-full text-sm">
      <thead className="text-left text-xs uppercase text-muted-foreground border-b">
        <tr>
          <th className="px-3 py-2">Title</th>
          <th className="px-3 py-2">Severity</th>
          <th className="px-3 py-2">Logsource</th>
          <th className="px-3 py-2">ATT&amp;CK</th>
          <th className="px-3 py-2 text-right">24h alerts</th>
          <th className="px-3 py-2 text-right">Lifetime matches</th>
          <th className="px-3 py-2">Status</th>
        </tr>
      </thead>
      <tbody>
        {rules.map((r) => (
          <RuleRow key={r.rule_id} rule={r} onSelect={onSelect} onToggle={onToggle} />
        ))}
      </tbody>
    </table>
  );
}
