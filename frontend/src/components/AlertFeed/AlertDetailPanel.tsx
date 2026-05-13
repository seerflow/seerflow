import { useEffect, useState } from "react";
import type { Alert, AlertDetail, FeedbackEvent, FeedbackHistoryResponse } from "@/lib/types";
import { api, ApiError } from "@/lib/api";
import { AlertDetailSchema, FeedbackEventSchema } from "@/lib/schemas";
import { Button } from "@/components/ui/button";
import { logger } from "@/lib/logger";
import { submitFeedback } from "@/lib/feedback";
import { useAlertStore } from "@/stores/alerts";
import { FeedbackHistory } from "./FeedbackHistory";

interface Props {
  alert: Alert;
}

export function AlertDetailPanel({ alert }: Props): JSX.Element {
  const [detail, setDetail] = useState<AlertDetail | null>(null);
  const [history, setHistory] = useState<FeedbackEvent[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const version = useAlertStore(s => s.feedbackVersion[alert.alert_id] ?? 0);

  useEffect(() => {
    let cancelled = false;
    // Scalar schema opt-in: api.ts::request runs v.safeParse against
    // AlertDetailSchema and throws ApiError(0, "response-schema-fail: …") when
    // the REST payload violates the contract. That surfaces through setErr
    // below exactly like any other transport failure (S-191 I-1).
    api.get<AlertDetail>(`/api/v1/alerts/${alert.alert_id}`, { schema: AlertDetailSchema })
      .then(d => { if (!cancelled) setDetail(d); })
      .catch((e: unknown) => {
        if (cancelled) return;
        setErr(e instanceof ApiError ? e.message : "Failed to load alert detail");
      });
    return () => { cancelled = true; };
  }, [alert.alert_id]);

  useEffect(() => {
    let cancelled = false;
    // S-210: schema opt-in catches malformed history rows. `itemsKey: "items"`
    // engages the per-row drop branch in api.ts::request — invalid rows are
    // dropped and a per-alert metric `rest:/api/v1/alerts/<alert_id>/feedback`
    // increments via incrementDropped().
    api.get<FeedbackHistoryResponse>(
      `/api/v1/alerts/${alert.alert_id}/feedback`,
      { schema: FeedbackEventSchema, itemsKey: "items" },
    )
      .then(p => { if (!cancelled) setHistory(p.items); })
      .catch((e: unknown) => { if (!cancelled) logger.warn("history load failed", e); });
    return () => { cancelled = true; };
  }, [alert.alert_id, version]);

  if (err) return <div role="alert" className="p-4 text-red-600">Error: {err}</div>;
  if (!detail) return <div className="p-4 text-muted-foreground">Loading…</div>;

  const submit = (f: "tp" | "fp"): void => { void submitFeedback(alert.alert_id, f); };

  return (
    <div id={`alert-detail-${alert.alert_id}`} className="flex flex-col gap-3 p-4 border-l bg-background/50">
      <h3 className="font-semibold">{detail.rule_name}</h3>
      <p className="text-sm">{detail.message}</p>
      {(detail.entity_value || detail.entity_type) && (
        <div className="flex flex-wrap gap-1" aria-label="entity references">
          {detail.entity_type && (
            <span className="rounded border bg-muted/30 px-2 py-0.5 text-xs font-mono">
              {detail.entity_type}{detail.entity_value ? `: ${detail.entity_value}` : ""}
            </span>
          )}
        </div>
      )}
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
      <section className="pt-2 border-t" aria-label="feedback history section">
        <h4 className="text-xs uppercase opacity-70 mb-1">Feedback history</h4>
        <FeedbackHistory items={history} />
      </section>
    </div>
  );
}
