"""URL masking helpers for alerting surfaces.

Used by the webhook dispatcher (for safe logging) and the config endpoint
(for redaction of webhook URLs that may contain embedded auth tokens).
"""

from __future__ import annotations

from urllib.parse import urlparse


def mask_webhook_url(url: str) -> str:
    """Return a host-only form of a webhook URL, hiding path and query.

    Webhook URLs from Slack/Teams/PagerDuty often embed tokens directly in
    the path (e.g. ``/services/T123/B456/SECRET``). This helper strips the
    path and query so the URL can be safely logged or returned to operators.
    """
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.hostname:
        return "<invalid-url>"
    return f"{parsed.scheme}://{parsed.hostname}/***"
