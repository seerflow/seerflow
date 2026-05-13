// S-151: One row in the Sigma rules table.
import type { SigmaRuleSummary } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { severityLabel } from "./severity";

interface Props {
  rule: SigmaRuleSummary;
  onSelect: (ruleId: string) => void;
  onToggle: (ruleId: string, enabled: boolean) => void;
}

export function RuleRow({ rule, onSelect, onToggle }: Props): JSX.Element {
  const handleRowClick = () => onSelect(rule.rule_id);
  const handleToggle = (e: React.ChangeEvent<HTMLInputElement>) =>
    onToggle(rule.rule_id, e.target.checked);

  return (
    <tr
      className="border-b hover:bg-muted/30 cursor-pointer text-sm"
      onClick={handleRowClick}
      data-testid={`sigma-rule-row-${rule.rule_id}`}
    >
      <td className="px-3 py-2">
        <span className="font-medium">{rule.title}</span>
      </td>
      <td className="px-3 py-2">
        <Badge variant="outline">{severityLabel(rule.severity)}</Badge>
      </td>
      <td className="px-3 py-2 text-muted-foreground">
        {rule.logsource_key.filter(Boolean).join(" / ") || "—"}
      </td>
      <td className="px-3 py-2 text-xs">
        {rule.attack_techniques.length > 0
          ? rule.attack_techniques.slice(0, 3).join(", ") +
            (rule.attack_techniques.length > 3 ? "…" : "")
          : "—"}
      </td>
      <td className="px-3 py-2 text-right tabular-nums">{rule.alert_count_24h}</td>
      <td className="px-3 py-2 text-right tabular-nums">
        {rule.match_count_lifetime}
      </td>
      <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
        <label className="inline-flex items-center cursor-pointer">
          <input
            type="checkbox"
            role="switch"
            aria-label={`Toggle rule ${rule.title}`}
            checked={rule.enabled}
            onChange={handleToggle}
            className="h-4 w-4 cursor-pointer accent-primary"
          />
        </label>
      </td>
    </tr>
  );
}
