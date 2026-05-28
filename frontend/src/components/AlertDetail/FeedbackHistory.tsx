import type { FeedbackEvent } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Props { items: FeedbackEvent[] }

// S-349: the `emerald-100/800` (tp) and `amber-100/800` (fp) badges were fixed
// light-palette literals with no dark-theme variant — they read muddy on the
// dark `--bg`. Migrated to brand semantic tokens: `info` (--info) for the
// true-positive badge and `warn` (--warn) for the false-positive badge, both of
// which flip between the dark `:root` and `.sf-light` themes.
const BADGE_CLASS: Record<"tp" | "fp", string> = {
  tp: "bg-info/15 text-info border-info/40",
  fp: "bg-warn/15 text-warn border-warn/40",
};

function formatRelative(ns: bigint): string {
  const deltaSec = Number((BigInt(Date.now()) * 1_000_000n - ns) / 1_000_000_000n);
  const fmt = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  if (deltaSec < 60) return fmt.format(-Math.round(deltaSec), "second");
  if (deltaSec < 3600) return fmt.format(-Math.round(deltaSec / 60), "minute");
  if (deltaSec < 86400) return fmt.format(-Math.round(deltaSec / 3600), "hour");
  return fmt.format(-Math.round(deltaSec / 86400), "day");
}

export function FeedbackHistory({ items }: Props): JSX.Element {
  if (items.length === 0) {
    return <p className="text-xs text-muted-foreground">No feedback yet</p>;
  }
  return (
    <ul className="flex flex-col gap-1" aria-label="feedback history">
      {items.map(ev => (
        <li
          key={ev.id}
          data-testid="feedback-history-row"
          className="flex items-center gap-2 text-xs"
        >
          <span className={cn("rounded border px-1.5 py-0.5 font-mono uppercase", BADGE_CLASS[ev.feedback])}>
            {ev.feedback}
          </span>
          <span className="rounded border px-1.5 py-0.5 text-[10px] uppercase opacity-70">
            {ev.origin}
          </span>
          <span className="text-muted-foreground">{formatRelative(ev.submitted_at_ns)}</span>
          {ev.note && <span className="truncate opacity-80">— {ev.note}</span>}
        </li>
      ))}
    </ul>
  );
}
