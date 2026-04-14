import { useEffect, useState } from "react";
import type { Alert, AlertDetail, Feedback } from "@/lib/types";
import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { logger } from "@/lib/logger";

interface Props {
  alert: Alert;
  onFeedback: (id: string, f: Feedback) => void;
}

export function AlertDetailPanel({ alert, onFeedback }: Props): JSX.Element {
  const [detail, setDetail] = useState<AlertDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.get<AlertDetail>(`/api/v1/alerts/${alert.alert_id}`)
      .then(d => { if (!cancelled) setDetail(d); })
      .catch((e: ApiError) => { if (!cancelled) setErr(e.message); });
    return () => { cancelled = true; };
  }, [alert.alert_id]);

  const submit = async (f: Feedback): Promise<void> => {
    const prev = alert.feedback ?? "";
    onFeedback(alert.alert_id, f);
    try {
      await api.post(`/api/v1/alerts/${alert.alert_id}/feedback`, { feedback: f });
    } catch (e) {
      logger.warn("feedback failed", e);
      onFeedback(alert.alert_id, prev);
    }
  };

  if (err) return <div role="alert" className="p-4 text-red-600">Error: {err}</div>;
  if (!detail) return <div className="p-4 text-muted-foreground">Loading…</div>;

  return (
    <div className="flex flex-col gap-3 p-4 border-l bg-background/50">
      <h3 className="font-semibold">{detail.rule_name}</h3>
      <p className="text-sm">{detail.message}</p>
      <div className="flex flex-wrap gap-1">
        {detail.mitre_tactics.map(t => <span key={t} className="rounded border px-2 py-0.5 text-xs">{t}</span>)}
        {detail.mitre_techniques.map(t => <span key={t} className="rounded border px-2 py-0.5 text-xs opacity-70">{t}</span>)}
      </div>
      <div className="text-sm">Risk score: <span className="font-mono">{detail.risk_score.toFixed(2)}</span></div>
      {detail.contributing_events && (
        <ul className="space-y-1 text-xs">
          {detail.contributing_events.map(e => <li key={e.event_id}>{e.message}</li>)}
        </ul>
      )}
      <div className="flex gap-2 pt-2 border-t">
        <Button size="sm" variant={alert.feedback === "tp" ? "default" : "outline"} aria-label="True positive" onClick={() => submit("tp")}>TP</Button>
        <Button size="sm" variant={alert.feedback === "fp" ? "default" : "outline"} aria-label="False positive" onClick={() => submit("fp")}>FP</Button>
      </div>
    </div>
  );
}
