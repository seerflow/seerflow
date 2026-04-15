import type { TimelineRange } from "@/lib/types";
import { cn } from "@/lib/utils";

const RANGES: TimelineRange[] = ["1h", "6h", "24h", "7d"];

interface Props {
  value: TimelineRange;
  onChange: (r: TimelineRange) => void;
}

export function TimeRangeChips({ value, onChange }: Props): JSX.Element {
  return (
    <div role="group" aria-label="Time range" className="flex gap-1">
      {RANGES.map((r) => (
        <button
          key={r}
          type="button"
          aria-pressed={value === r}
          onClick={() => onChange(r)}
          className={cn(
            "px-2 py-1 text-xs rounded border",
            value === r
              ? "bg-accent text-accent-foreground border-accent"
              : "border-border",
          )}
        >
          {r}
        </button>
      ))}
      <button
        type="button"
        disabled
        title="Coming soon"
        aria-label="Custom…"
        className="px-2 py-1 text-xs rounded border border-border opacity-50 cursor-not-allowed"
      >
        Custom…
      </button>
    </div>
  );
}
