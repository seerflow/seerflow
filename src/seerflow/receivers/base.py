"""Receiver Protocol and RawEvent model for the ingestion layer."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Receiver(Protocol):  # pragma: no cover
    """Async log ingestion source.

    All receivers implement this Protocol. ReceiverManager orchestrates
    lifecycle and feeds events into a shared queue.
    """

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def is_healthy(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class RawEvent:
    """Raw log bytes + metadata from a receiver.

    This is the boundary between ingestion (receivers) and processing
    (parser, entity extraction). All receivers produce RawEvent instances.
    """

    data: bytes
    source_type: str
    source_id: str
    received_ns: int
    metadata: dict[str, Any]
