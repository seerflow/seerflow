"""WhatsApp Business Cloud API DeliveryTarget (S-163)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from time import monotonic
from typing import TYPE_CHECKING

from seerflow.alerting._http import RetryDecision, post_with_retry, sanitize_body
from seerflow.alerting.channels._format import severity_name as _sev_name
from seerflow.alerting.channels._ratelimit import TokenBucket

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    import aiohttp

    from seerflow.models.alert import Alert

_log = logging.getLogger("seerflow")

_WA_HOST = "graph.facebook.com"
_WA_API_VERSION = "v18.0"
_CIRCUIT_OPEN_SECONDS = 300.0
_TEMPLATE_NOT_FOUND = 131026


def build_template_params(alert: Alert) -> list[dict[str, str]]:
    return [
        {"type": "text", "text": _sev_name(int(alert.severity_id))},
        {"type": "text", "text": alert.rule_name},
        {"type": "text", "text": alert.entity_value},
    ]


class _CircuitState:
    __slots__ = ("open_until",)

    def __init__(self) -> None:
        self.open_until: float = 0.0


@dataclass(frozen=True, slots=True, kw_only=True)
class WhatsAppTarget:
    """WhatsApp Cloud API DeliveryTarget. ``access_token`` hidden from ``repr``."""

    name: str
    phone_number_id: str
    template_name: str
    language_code: str
    to_numbers: tuple[str, ...]
    access_token: str = field(default="", repr=False)
    min_severity: int = 0
    rate_per_second: float = 10.0
    burst: int = 20
    _monotonic: Callable[[], float] = field(default=monotonic, repr=False)
    _bucket: TokenBucket = field(init=False, repr=False, compare=False)
    _circuit: _CircuitState = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_bucket", TokenBucket(self.rate_per_second, self.burst))
        object.__setattr__(self, "_circuit", _CircuitState())

    def _url(self) -> str:
        return f"https://{_WA_HOST}/{_WA_API_VERSION}/{self.phone_number_id}/messages"

    def _payload_for(self, alert: Alert, to: str) -> dict[str, object]:
        return {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": self.template_name,
                "language": {"code": self.language_code},
                "components": [
                    {"type": "body", "parameters": build_template_params(alert)},
                ],
            },
        }

    async def _post_one(self, session: aiohttp.ClientSession, alert: Alert, to: str) -> None:
        now = self._monotonic()
        if now < self._circuit.open_until:
            _log.info(
                "WhatsApp %s: circuit open, dropping alert %s",
                self.name,
                alert.alert_id,
            )
            return
        await self._bucket.acquire()
        headers = {"Authorization": f"Bearer {self.access_token}"}
        await post_with_retry(
            session,
            self._url(),
            self._payload_for(alert, to),
            masked_for_log=f"whatsapp/{self.name}",
            headers=headers,
            timeout_seconds=10.0,
            body_inspector=self._inspect_response,
        )

    def _inspect_response(self, status: int, body_text: str) -> RetryDecision:
        """Open the 5-minute circuit on Meta error code 131026; otherwise defer.

        For non-131026 4xx responses the Meta-specific ``error.code`` is logged
        here so operators retain the diagnostic field that the original
        hand-rolled ``_post_one`` exposed before this path was routed through
        ``post_with_retry``. 5xx responses are intentionally NOT escalated to
        ERROR even when they carry a Meta ``code`` field — they will be retried,
        and ``post_with_retry`` already logs each attempt at WARNING and the
        final exhaustion at ERROR. Logging here too would triple-log a transient
        outage at ERROR severity and trigger operator alert fatigue.
        """
        try:
            body = json.loads(body_text)
        except ValueError:
            body = {}
        # Two-step guard: a non-dict ``body["error"]`` (e.g. a list from a
        # compromised upstream) would otherwise raise AttributeError on the
        # nested ``.get()`` and convert a terminal 4xx into a retried failure.
        err = body.get("error") if isinstance(body, dict) else None
        code = err.get("code") if isinstance(err, dict) else None
        if code == _TEMPLATE_NOT_FOUND:
            self._circuit.open_until = self._monotonic() + _CIRCUIT_OPEN_SECONDS
            _log.error(
                "WhatsApp %s: template %r not found (131026) - circuit open for %ds",
                self.name,
                self.template_name,
                int(_CIRCUIT_OPEN_SECONDS),
            )
            return "stop"
        if code is not None and status < 500:
            # Inspector owns the log: returning "stop" prevents post_with_retry
            # from also logging the same response body via _handle_response.
            # ``code`` is sanitised because a compromised upstream could place
            # control characters or ANSI escapes in the field.
            _log.error(
                "WhatsApp %s: delivery failed status=%d code=%s",
                self.name,
                status,
                sanitize_body(str(code), max_len=64),
            )
            return "stop"
        return "default"

    async def deliver(self, alert: Alert, *, session: aiohttp.ClientSession) -> None:
        for to in self.to_numbers:
            await self._post_one(session, alert, to)

    async def deliver_digest(
        self, alerts: Sequence[Alert], *, session: aiohttp.ClientSession
    ) -> None:
        if not alerts:
            return
        top = max(alerts, key=lambda a: int(a.severity_id))
        await self.deliver(top, session=session)
