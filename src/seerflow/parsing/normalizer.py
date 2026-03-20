"""Field normalization — RawEvent → SeerflowEvent.

NOT thread-safe — wraps DrainParser which mutates internal state.
Create one instance per thread/coroutine or protect with a lock.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING

from seerflow.models.event import SeerflowEvent, SeverityLevel
from seerflow.parsing.drain import DrainParser
from seerflow.parsing.entities import EntityExtractor

if TYPE_CHECKING:
    from seerflow.receivers.base import RawEvent

_log = logging.getLogger(__name__)

_MAX_MESSAGE_LEN = 32_768
_USED_ENTITY_TYPES = frozenset({"ip", "user", "host"})


class EventNormalizer:
    """Transforms RawEvent into SeerflowEvent.

    Composes DrainParser (template extraction) and EntityExtractor
    (IP, user, host extraction) to populate all fields.

    NOT thread-safe — wraps DrainParser which mutates internal state.
    Create one instance per thread/coroutine or protect with a lock.
    """

    __slots__ = ("_extractor", "_parser")

    def __init__(
        self,
        *,
        drain_parser: DrainParser | None = None,
        entity_extractor: EntityExtractor | None = None,
    ) -> None:
        self._parser = drain_parser or DrainParser()
        self._extractor = entity_extractor or EntityExtractor(
            enabled_types=_USED_ENTITY_TYPES,
        )

    def normalize(self, raw: RawEvent) -> SeerflowEvent:
        """Convert a RawEvent to a SeerflowEvent."""
        observed_ns = time.time_ns()

        message = raw.data.decode("utf-8", errors="replace")
        if len(message) > _MAX_MESSAGE_LEN:
            message = message[:_MAX_MESSAGE_LEN]

        # Severity from metadata (set by SyslogReceiver) or default
        sev_value = raw.metadata.get("seerflow_severity", 1)
        try:
            severity = SeverityLevel(sev_value)
        except (ValueError, KeyError):
            _log.warning("Invalid seerflow_severity=%r, defaulting to INFORMATIONAL", sev_value)
            severity = SeverityLevel.INFORMATIONAL

        # Template extraction
        template_id, template_str, template_params = self._parser.parse(message)

        # Entity extraction
        entities = self._extractor.extract(message)

        return SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=raw.received_ns,
            observed_ns=observed_ns,
            severity_id=severity,
            message=message,
            source_type=raw.source_type,
            source_id=raw.source_id,
            template_id=template_id,
            template_str=template_str,
            template_params=template_params,
            related_ips=tuple(entities.get("ip", [])),
            related_users=tuple(entities.get("user", [])),
            related_hosts=tuple(entities.get("host", [])),
        )
