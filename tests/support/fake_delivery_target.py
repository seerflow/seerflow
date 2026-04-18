"""In-memory DeliveryTarget used across router unit + integration tests."""

from __future__ import annotations

from dataclasses import dataclass, field

from seerflow.models.alert import Alert


@dataclass
class FakeDeliveryTarget:
    """Records every delivered alert + every digest batch."""

    name: str
    min_severity: int = 0
    delivered: list[Alert] = field(default_factory=list)
    digests: list[list[Alert]] = field(default_factory=list)
    deliver_raises: Exception | None = None
    digest_raises: Exception | None = None

    async def deliver(self, alert: Alert) -> None:
        if self.deliver_raises is not None:
            raise self.deliver_raises
        self.delivered.append(alert)

    async def deliver_digest(self, alerts: list[Alert]) -> None:
        if self.digest_raises is not None:
            raise self.digest_raises
        self.digests.append(list(alerts))
