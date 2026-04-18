"""S-163 delivery channels (email, SMS, Telegram, WhatsApp)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from seerflow.alerting.channels.email import EmailTarget
from seerflow.alerting.channels.sms import SmsTarget
from seerflow.alerting.channels.telegram import TelegramTarget
from seerflow.alerting.channels.whatsapp import WhatsAppTarget

if TYPE_CHECKING:
    from collections.abc import Sequence

    import aiohttp

    from seerflow.models.alert import Alert


class _HttpChannel(Protocol):
    """Structural subset of SmsTarget/TelegramTarget/WhatsAppTarget.

    These channels take a shared ``aiohttp.ClientSession`` as a keyword
    argument on ``deliver`` / ``deliver_digest`` so the session lifecycle
    lives in ``run.py``. :func:`bind_http_channel` wraps them to satisfy
    the session-less ``DeliveryTarget`` protocol used by
    :class:`~seerflow.alerting.router.NotificationRouter`.
    """

    name: str
    min_severity: int

    async def deliver(
        self, alert: Alert, *, session: aiohttp.ClientSession
    ) -> None: ...  # pragma: no cover

    async def deliver_digest(
        self, alerts: Sequence[Alert], *, session: aiohttp.ClientSession
    ) -> None: ...  # pragma: no cover


@dataclass(frozen=True, slots=True)
class _HttpChannelBound:
    """Binds a shared aiohttp session to an HTTP channel target."""

    name: str
    min_severity: int
    _channel: _HttpChannel = field(repr=False)
    _session: aiohttp.ClientSession = field(repr=False)

    async def deliver(self, alert: Alert) -> None:
        await self._channel.deliver(alert, session=self._session)

    async def deliver_digest(self, alerts: Sequence[Alert]) -> None:
        await self._channel.deliver_digest(alerts, session=self._session)


def bind_http_channel(
    channel: _HttpChannel, *, session: aiohttp.ClientSession
) -> _HttpChannelBound:
    """Wrap ``channel`` so it satisfies the session-less ``DeliveryTarget``
    contract used by :class:`NotificationRouter`.
    """
    return _HttpChannelBound(
        name=channel.name,
        min_severity=channel.min_severity,
        _channel=channel,
        _session=session,
    )


__all__ = [
    "EmailTarget",
    "SmsTarget",
    "TelegramTarget",
    "WhatsAppTarget",
    "bind_http_channel",
]
