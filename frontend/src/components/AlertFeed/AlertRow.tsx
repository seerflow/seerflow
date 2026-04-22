import { memo, type MouseEvent } from "react";
import type { Alert, Feedback } from "@/lib/types";
import { severityBucket, SEVERITY_CLASS, SEVERITY_LABEL } from "@/lib/severity";
import { cn } from "@/lib/utils";
import { submitFeedback } from "@/lib/feedback";

interface Props { alert: Alert; onClick: (id: string) => void; isOpen?: boolean }

function FeedbackIconButton(
  { verdict, active, alertId }:
  { verdict: Exclude<Feedback, "">; active: boolean; alertId: string },
): JSX.Element {
  const label = verdict === "tp" ? "mark true positive" : "mark false positive";
  const glyph = verdict === "tp" ? "✓" : "✗";
  const color = verdict === "tp"
    ? "text-emerald-600 border-emerald-600"
    : "text-amber-600 border-amber-600";
  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={active}
      onClick={(e: MouseEvent) => {
        e.stopPropagation();
        void submitFeedback(alertId, verdict);
      }}
      className={cn(
        "rounded border px-1.5 py-0.5 text-xs hover:bg-muted/40",
        active ? `${color} bg-muted/60` : "opacity-60",
      )}
    >{glyph}</button>
  );
}

function Row({ alert, onClick, isOpen }: Props): JSX.Element {
  const bucket = severityBucket(alert.severity);
  const ts = new Date(Number(alert.timestamp_ns / 1_000_000n)).toISOString().slice(11, 19);
  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`alert ${alert.rule_name}`}
      aria-expanded={isOpen ?? false}
      aria-controls={`alert-detail-${alert.alert_id}`}
      onClick={() => onClick(alert.alert_id)}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onClick(alert.alert_id); }}
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
      <div className="flex gap-1 ml-2">
        <FeedbackIconButton verdict="tp" active={alert.feedback === "tp"} alertId={alert.alert_id} />
        <FeedbackIconButton verdict="fp" active={alert.feedback === "fp"} alertId={alert.alert_id} />
      </div>
    </div>
  );
}

export const AlertRow = memo(Row);
