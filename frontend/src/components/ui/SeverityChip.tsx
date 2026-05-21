// S-231 / SEE-256: shared severity-chip presentational primitive.
//
// Extracted from the duplicated chip markup in `SigmaRules/FilterBar` and
// `AlertFeed/FilterBar` (visually unified by S-230, but two independent
// implementations). The contract is intentionally value-agnostic: a chip is
// just a `label`, an `active` flag, and an `onToggle` callback. Each FilterBar
// keeps its own severity value model (Sigma: `severity_in: number[]` OCSF
// numeric; AlertFeed: `severities: Set<SeverityBucket>` string buckets) and
// adapts to this contract at its call site, so no store / wire / query-param
// behavior changes.
//
// Markup is byte-identical to the post-S-230 Sigma chip. `capitalize` is a
// CSS-only transform — the DOM text is the raw `label`, so callers that need
// an exact accessible name (e.g. AlertFeed) pass an already-cased label.
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface SeverityChipProps {
  label: string;
  active: boolean;
  onToggle: () => void;
}

export function SeverityChip({
  label,
  active,
  onToggle,
}: SeverityChipProps): JSX.Element {
  return (
    <Button
      type="button"
      size="sm"
      variant="outline"
      aria-pressed={active}
      className={cn("capitalize", active && "bg-primary text-primary-foreground")}
      onClick={onToggle}
    >
      {label}
    </Button>
  );
}
