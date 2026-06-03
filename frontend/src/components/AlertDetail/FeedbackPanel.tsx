import React, { useCallback, useEffect, useState } from "react";
import * as v from "valibot";
import { api } from "@/lib/api";
import { submitFeedback } from "@/lib/feedback";
import { useAlertStore } from "@/stores/alerts";
import {
  FeedbackHistoryResponseSchema,
  type FeedbackHistoryResponseInfer,
} from "@/lib/schemas";
import { FeedbackHistory } from "./FeedbackHistory";
import { Button } from "@/components/ui/button";
import { logger } from "@/lib/logger";

const HISTORY_LIMIT = 5;

export interface FeedbackPanelProps {
  /** Alert whose verdict + history this panel manages. */
  alertId: string;
}

/**
 * S-339: TP/FP verdict + recent-history block, mounted in the right rail of
 * the alert detail page (above Entities). The buttons delegate to the existing
 * `submitFeedback` helper (`lib/feedback.ts`) — which owns the optimistic
 * store update + 5xx rollback + toast. Pressed visual is derived from the live
 * store `alert.feedback` value, so the optimistic fill is synchronous and
 * rollback is automatic when the helper reverts the store.
 *
 * The history below the buttons is fetched from
 * `GET /api/v1/alerts/{id}/feedback?limit=5`, validated by
 * `FeedbackHistoryResponseSchema`, and re-fetched whenever
 * `feedbackVersion[alertId]` bumps (i.e. after every successful submit).
 */
export const FeedbackPanel: React.FC<FeedbackPanelProps> = ({ alertId }) => {
  const verdict = useAlertStore(
    (s) => s.alerts.find((a) => a.alert_id === alertId)?.feedback ?? null,
  );
  const version = useAlertStore((s) => s.feedbackVersion[alertId] ?? 0);

  const [history, setHistory] = useState<FeedbackHistoryResponseInfer | null>(
    null,
  );
  const [pending, setPending] = useState(false);

  // Refetch history on mount, on alert change, and after every successful
  // feedback submit (via the `feedbackVersion[alertId]` bump).
  useEffect(() => {
    const ctrl = new AbortController();
    let cancelled = false;
    void api
      .get<FeedbackHistoryResponseInfer>(
        `/api/v1/alerts/${alertId}/feedback?limit=${HISTORY_LIMIT}`,
        { signal: ctrl.signal, schema: FeedbackHistoryResponseSchema },
      )
      .then((resp) => {
        if (cancelled) return;
        // Belt-and-braces: the api client schema-validates, but a manual parse
        // here guards against future refactors that drop the opts.schema arg.
        const parsed = v.safeParse(FeedbackHistoryResponseSchema, resp);
        if (parsed.success) {
          setHistory(parsed.output);
        }
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        logger.warn("feedback history fetch failed", e);
        // Leave history null → empty placeholder renders.
      });
    return () => {
      cancelled = true;
      ctrl.abort();
    };
  }, [alertId, version]);

  const handleClick = useCallback(
    async (next: "tp" | "fp") => {
      if (pending) return;
      setPending(true);
      try {
        await submitFeedback(alertId, next);
      } finally {
        setPending(false);
      }
    },
    [alertId, pending],
  );

  const items = history?.items ?? [];
  const total = history?.total ?? 0;
  const overflow = Math.max(0, total - items.length);

  return (
    <div className="flex flex-col gap-3" data-testid="feedback-panel">
      <div className="flex items-center gap-2">
        <Button
          type="button"
          size="sm"
          variant={verdict === "tp" ? "default" : "outline"}
          aria-label="true positive"
          aria-pressed={verdict === "tp"}
          disabled={pending}
          onClick={() => void handleClick("tp")}
        >
          True positive
        </Button>
        <Button
          type="button"
          size="sm"
          variant={verdict === "fp" ? "default" : "outline"}
          aria-label="false positive"
          aria-pressed={verdict === "fp"}
          disabled={pending}
          onClick={() => void handleClick("fp")}
        >
          False positive
        </Button>
      </div>
      <div className="flex flex-col gap-1.5">
        <FeedbackHistory items={items} />
        {overflow > 0 && (
          <span className="text-[10.5px] text-text-3">
            +{overflow} more
          </span>
        )}
      </div>
    </div>
  );
};
