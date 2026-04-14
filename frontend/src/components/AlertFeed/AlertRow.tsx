import { memo } from "react";
import type { Alert } from "@/lib/types";
import { severityBucket, SEVERITY_CLASS, SEVERITY_LABEL } from "@/lib/severity";
import { cn } from "@/lib/utils";

interface Props { alert: Alert; onClick: (id: string) => void; isOpen?: boolean }

function Row({ alert, onClick, isOpen }: Props): JSX.Element {
  const bucket = severityBucket(alert.severity);
  const ts = new Date(Math.floor(alert.timestamp_ns / 1_000_000)).toISOString().slice(11, 19);
  return (
    <button
      type="button"
      aria-label={`alert ${alert.rule_name}`}
      aria-expanded={isOpen ?? false}
      onClick={() => onClick(alert.alert_id)}
      className={cn(
        "w-full flex items-center gap-3 border-l-4 px-3 py-2 text-left hover:bg-muted/40 focus:outline-none focus:ring-2 focus:ring-ring",
        SEVERITY_CLASS[bucket],
      )}
    >
      <span className="min-w-[72px] font-mono text-xs opacity-70">{ts}</span>
      <span className={cn("rounded border px-1.5 py-0.5 text-xs", SEVERITY_CLASS[bucket])}>{SEVERITY_LABEL[bucket]}</span>
      <span className="uppercase text-[10px] opacity-70 min-w-[64px]">{alert.alert_type}</span>
      <span className="truncate flex-1">{alert.rule_name}</span>
      {alert.entity_value && <span className="font-mono text-xs truncate max-w-[160px]">{alert.entity_value}</span>}
    </button>
  );
}

export const AlertRow = memo(Row);
