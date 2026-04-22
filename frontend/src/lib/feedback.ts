import { toast } from "sonner";
import type { Feedback } from "@/lib/types";
import { api, ApiError } from "@/lib/api";
import { useAlertStore } from "@/stores/alerts";
import { logger } from "@/lib/logger";

const LABEL: Record<Exclude<Feedback, "">, string> = {
  tp: "true positive",
  fp: "false positive",
};

// Product-defined toast durations (S-066). Kept as module-level constants
// so `submitFeedback` — a plain function, not a React component — can call
// `toast.*` directly without going through the `useToast` hook.
const SUCCESS_MS = 3000;
const ERROR_MS = 5000;

export async function submitFeedback(
  alertId: string,
  verdict: Exclude<Feedback, "">,
): Promise<void> {
  const store = useAlertStore.getState();
  const prev = store.alerts.find(a => a.alert_id === alertId)?.feedback ?? "";
  store.setFeedback(alertId, verdict);

  try {
    await api.post(`/api/v1/alerts/${alertId}/feedback`, {
      feedback: verdict,
      origin: "dashboard",
    });
    useAlertStore.getState().bumpFeedbackVersion(alertId);
    toast.success(`Marked as ${LABEL[verdict]}`, { duration: SUCCESS_MS });
  } catch (err) {
    logger.warn("feedback failed", err);
    useAlertStore.getState().setFeedback(alertId, prev);
    const msg = err instanceof ApiError && err.status === 404
      ? "Alert no longer exists"
      : "Feedback failed — retry";
    toast.error(msg, { duration: ERROR_MS });
  }
}
