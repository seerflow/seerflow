"""WhatsApp Business Cloud API DeliveryTarget (S-163)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from time import monotonic
from typing import TYPE_CHECKING

import aiohttp

from seerflow.alerting.channels._format import severity_name as _sev_name
from seerflow.alerting.channels._ratelimit import TokenBucket

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

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
        try:
            async with session.post(
                self._url(),
                json=self._payload_for(alert, to),
                timeout=aiohttp.ClientTimeout(total=10),
                allow_redirects=False,
                headers=headers,
            ) as resp:
                if resp.status < 400:
                    return
                try:
                    body = await resp.json()
                except aiohttp.ContentTypeError:
                    body = {}
                code = (body.get("error") or {}).get("code")
                if code == _TEMPLATE_NOT_FOUND:
                    self._circuit.open_until = now + _CIRCUIT_OPEN_SECONDS
                    _log.error(
                        "WhatsApp %s: template %r not found (131026) — circuit open for %ds",
                        self.name,
                        self.template_name,
                        int(_CIRCUIT_OPEN_SECONDS),
                    )
                    return
                _log.error(
                    "WhatsApp %s: delivery failed status=%d code=%s",
                    self.name,
                    resp.status,
                    code,
                )
        except (aiohttp.ClientError, TimeoutError) as exc:
            # ``access_token`` sits in the Authorization header, so ``aiohttp``
            # exception strings should not echo it. Scrub defensively through
            # the shared helper in case a future aiohttp version changes that.
            from seerflow.alerting._http import _scrub_secrets

            _log.warning(
                "WhatsApp %s: transport error %s",
                self.name,
                _scrub_secrets(str(exc)),
            )

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
