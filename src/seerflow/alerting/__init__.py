"""Alert routing: dedup, webhooks, PagerDuty, OTLP, feedback."""

from seerflow.alerting.dispatcher import WebhookTarget

__all__ = ["WebhookTarget"]
