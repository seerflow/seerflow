import type { WsStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { SEVERITY_CLASS, SEVERITY_LABEL } from "@/lib/severity";

interface Counts { total: number; critical: number; high: number; medium: number; low: number }

export function SummaryBadges({ counts, status }: { counts: Counts; status: WsStatus }): JSX.Element {
  const dot = status === "open" ? "bg-emerald-500" : status === "connecting" ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-3 border-b px-3 py-2 text-sm">
      <span className="flex items-center gap-1"><span className={cn("inline-block h-2 w-2 rounded-full", dot)} aria-hidden /> <span className="text-muted-foreground">{status}</span></span>
      <span className="font-semibold">{counts.total}</span>
      {(["critical","high","medium","low"] as const).map(k => (
        <span key={k} className={cn("rounded border px-2 py-0.5", SEVERITY_CLASS[k])}>{SEVERITY_LABEL[k]} {counts[k]}</span>
      ))}
    </div>
  );
}
