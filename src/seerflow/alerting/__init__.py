"""Alert routing: dedup, webhooks, PagerDuty, OTLP, feedback."""

from seerflow.alerting.dispatcher import AlertDispatcher, WebhookTarget

__all__ = ["AlertDispatcher", "WebhookTarget"]
