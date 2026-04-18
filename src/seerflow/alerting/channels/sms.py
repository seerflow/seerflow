"""SMS DeliveryTarget — Twilio via raw aiohttp POST (S-163)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import aiohttp

from seerflow.alerting._http import post_with_retry
from seerflow.alerting.channels._ratelimit import TokenBucket

if TYPE_CHECKING:
    from collections.abc import Sequence

    from seerflow.models.alert import Alert

_TWILIO_HOST = "api.twilio.com"
_SMS_MAX = 1600

_SEVERITY_NAME: dict[int, str] = {
    0: "TRACE",
    1: "INFO",
    2: "NOTICE",
    3: "WARNING",
    4: "ERROR",
    5: "CRITICAL",
    6: "FATAL",
}


def _sev_name(sev: int) -> str:
    return _SEVERITY_NAME.get(sev, str(sev))


def _truncate(raw: str) -> str:
    if len(raw) <= _SMS_MAX:
        return raw
    return raw[: _SMS_MAX - 1] + "…"


def format_sms_body(alert: Alert) -> str:
    raw = (
        f"Seerflow [{_sev_name(int(alert.severity_id))}] "
        f"{alert.rule_name}: {alert.description} — "
        f"{alert.entity_value} ({alert.entity_type})"
    )
    return _truncate(raw)


def format_sms_digest(alerts: Sequence[Alert]) -> str:
    top = max(alerts, key=lambda a: int(a.severity_id))
    remaining = len(alerts) - 1
    base = f"Seerflow: {len(alerts)} new alerts — top: {format_sms_body(top)}"
    if remaining > 0:
        base += f" (+{remaining} more)"
    return _truncate(base)


@dataclass(frozen=True, slots=True, kw_only=True)
class SmsTarget:
    """Twilio SMS DeliveryTarget. ``auth_token`` hidden from ``repr``."""

    name: str
    account_sid: str
    from_number: str
    to_numbers: tuple[str, ...]
    auth_token: str = field(default="", repr=False)
    min_severity: int = 0
    rate_per_second: float = 1.0
    burst: int = 3
    _bucket: TokenBucket = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_bucket", TokenBucket(self.rate_per_second, self.burst))

    def _url(self) -> str:
        return f"https://{_TWILIO_HOST}/2010-04-01/Accounts/{self.account_sid}/Messages.json"

    def _masked(self) -> str:
        head = self.account_sid[:6] if len(self.account_sid) >= 6 else self.account_sid
        return f"twilio/{head}…"

    async def _post(self, session: aiohttp.ClientSession, body: str) -> None:
        auth = aiohttp.BasicAuth(self.account_sid, self.auth_token)
        for to in self.to_numbers:
            await self._bucket.acquire()
            await post_with_retry(
                session,
                self._url(),
                masked_for_log=self._masked(),
                auth=auth,
                data={"From": self.from_number, "To": to, "Body": body},
            )

    async def deliver(self, alert: Alert, *, session: aiohttp.ClientSession) -> None:
        await self._post(session, format_sms_body(alert))

    async def deliver_digest(
        self, alerts: Sequence[Alert], *, session: aiohttp.ClientSession
    ) -> None:
        if not alerts:
            return
        await self._post(session, format_sms_digest(alerts))
