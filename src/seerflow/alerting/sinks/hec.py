"""Splunk HTTP Event Collector (HEC) outbound sink (S-362/FR-001).

A synchronous-per-call HTTP :class:`~seerflow.alerting.target.DeliveryTarget`:
each :meth:`HecSink.deliver` POSTs one alert as ``{"event": <alert json>}`` to
``<base>/services/collector`` with the ``Authorization: Splunk <token>`` header.

:meth:`HecSink.deliver_digest` overrides the default per-alert loop to CONCATENATE
the per-alert JSON objects (``{"event":...}{"event":...}``) — the format the HEC
raw endpoint expects — rather than wrapping them in a JSON array, and sends the
whole batch in a single POST.

Security/robustness:
- The token is supplied by env-sourced config (``alerting.sinks[*].options.token``)
  and is NEVER hardcoded or logged: only the masked endpoint reaches the logs, and
  ``_http`` scrubs any ``Splunk <token>`` fragment from exception strings.
- TLS verification is on by default. A configured CA bundle builds a custom
  :class:`ssl.SSLContext`; verification is never disabled.
- Delivery reuses :func:`seerflow.alerting._http.post_with_retry`, so failures are
  retried with exponential backoff and a transport error can never block or crash
  the pipeline.
"""

from __future__ import annotations

import json
import ssl
from typing import TYPE_CHECKING

import aiohttp

from seerflow.alerting._http import post_with_retry
from seerflow.alerting.formatters import format_json
from seerflow.alerting.mask import mask_webhook_url

if TYPE_CHECKING:
    from collections.abc import Sequence

    from seerflow.models.alert import Alert

_COLLECTOR_PATH = "/services/collector"
_DEFAULT_RETRY_DELAYS: tuple[float, ...] = (1.0, 2.0, 4.0)
_DEFAULT_ATTEMPTS = 3
# Compact separators so concatenated objects stay tight: ``{"event":...}{...}``.
_COMPACT_SEPARATORS = (",", ":")


def _build_event_body(alert: Alert) -> dict[str, object]:
    """Wrap an alert's flat JSON representation in the HEC ``event`` envelope."""
    return {"event": format_json(alert)}


def _concatenate_events(alerts: Sequence[Alert]) -> bytes:
    """Serialize alerts as back-to-back HEC event objects (NOT a JSON array).

    Splunk HEC's raw event endpoint reads concatenated JSON objects from the
    request body, so we emit ``{"event":...}{"event":...}`` with no array
    brackets and no separator between objects.
    """
    return b"".join(
        json.dumps(_build_event_body(a), separators=_COMPACT_SEPARATORS).encode("utf-8")
        for a in alerts
    )


def _build_ssl_context(ca: str) -> ssl.SSLContext | None:
    """Build a verifying SSL context from a CA bundle path, or ``None``.

    Empty ``ca`` → ``None`` → aiohttp's default system-trust verification.
    A non-empty path produces a context that verifies the server against that
    CA bundle. Verification is never disabled.
    """
    if not ca:
        return None
    return ssl.create_default_context(cafile=ca)


class HecSink:
    """Outbound sink that forwards Seerflow alerts to a Splunk HEC endpoint.

    Satisfies the :class:`~seerflow.alerting.target.DeliveryTarget` protocol
    structurally (``name``/``min_severity`` read-only properties, async
    ``deliver``/``deliver_digest``).
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        name: str,
        min_severity: int = 0,
        ca: str = "",
        session: aiohttp.ClientSession | None = None,
        attempts: int = _DEFAULT_ATTEMPTS,
        retry_delays: tuple[float, ...] = _DEFAULT_RETRY_DELAYS,
    ) -> None:
        self._collector_url = f"{base_url.rstrip('/')}{_COLLECTOR_PATH}"
        self._masked = mask_webhook_url(base_url)
        # ``Authorization: Splunk <token>`` is the HEC auth scheme. The token is
        # held only in this header map; it is never logged (``post_with_retry``
        # logs the masked endpoint, and ``_http`` scrubs ``Splunk <token>``).
        self._headers = {
            "Authorization": f"Splunk {token}",
            "Content-Type": "application/json",
        }
        self._name = name
        self._min_severity = min_severity
        self._ssl_context = _build_ssl_context(ca)
        self._session = session
        self._owns_session = session is None
        self._attempts = attempts
        self._retry_delays = retry_delays

    @property
    def name(self) -> str:
        return self._name

    @property
    def min_severity(self) -> int:
        return self._min_severity

    def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
            self._owns_session = True
        return self._session

    async def _post(self, body: bytes) -> None:
        await post_with_retry(
            self._ensure_session(),
            self._collector_url,
            data=body,
            headers=self._headers,
            masked_for_log=self._masked,
            attempts=self._attempts,
            delays=self._retry_delays,
            ssl_context=self._ssl_context,
        )

    async def deliver(self, alert: Alert) -> None:
        """POST a single ``{"event": ...}`` object to the HEC collector."""
        body = json.dumps(_build_event_body(alert), separators=_COMPACT_SEPARATORS).encode("utf-8")
        await self._post(body)

    async def deliver_digest(self, alerts: Sequence[Alert]) -> None:
        """POST a concatenated-object batch in a single request.

        Overrides the default per-alert loop: HEC accepts concatenated JSON
        objects, so the whole digest travels in one POST instead of one POST
        per alert.
        """
        if not alerts:
            return
        await self._post(_concatenate_events(alerts))

    async def close(self) -> None:
        """Close the HTTP session if this sink created it."""
        if self._session is not None and self._owns_session:
            await self._session.close()
            self._session = None
