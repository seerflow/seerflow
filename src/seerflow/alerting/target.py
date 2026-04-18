"""DeliveryTarget protocol shared by webhooks and future channels (S-163)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence

    from seerflow.models.alert import Alert


@runtime_checkable
class DeliveryTarget(Protocol):
    """Any alerting sink the NotificationRouter can address by name.

    The ``name`` field must be unique across the configured targets.
    ``min_severity`` uses the 0-6 SeverityLevel scale from event.py.
    """

    name: str
    min_severity: int

    async def deliver(self, alert: Alert) -> None: ...  # pragma: no cover

    async def deliver_digest(self, alerts: Sequence[Alert]) -> None: ...  # pragma: no cover


async def loop_deliver_digest(target: DeliveryTarget, alerts: Sequence[Alert]) -> None:
    """Default ``deliver_digest`` implementation: loops ``deliver`` per alert.

    Concrete targets (WebhookTarget, future email/SMS channels) may override
    to build a genuine batched payload. Exposed as a free function so
    WebhookTarget's method body can delegate here without duplicating logic.
    """
    for alert in alerts:
        await target.deliver(alert)
