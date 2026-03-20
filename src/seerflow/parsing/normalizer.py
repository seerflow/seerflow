"""Field normalization — RawEvent → SeerflowEvent."""
from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

from seerflow.models.event import SeerflowEvent, SeverityLevel
from seerflow.parsing.drain import DrainParser
from seerflow.parsing.entities import EntityExtractor

if TYPE_CHECKING:
    from seerflow.receivers.base import RawEvent


class EventNormalizer:
    """Transforms RawEvent into SeerflowEvent.

    Composes DrainParser (template extraction) and EntityExtractor
    (IP, user, host, file, domain extraction) to populate all fields.
    """

    __slots__ = ("_extractor", "_parser")

    def __init__(
        self,
        *,
        drain_parser: DrainParser | None = None,
        entity_extractor: EntityExtractor | None = None,
    ) -> None:
        self._parser = drain_parser or DrainParser()
        self._extractor = entity_extractor or EntityExtractor()

    def normalize(self, raw: RawEvent) -> SeerflowEvent:
        """Convert a RawEvent to a SeerflowEvent."""
        message = raw.data.decode("utf-8", errors="replace")

        # Severity from metadata (set by SyslogReceiver) or default
        sev_value = raw.metadata.get("seerflow_severity", 1)
        severity = SeverityLevel(sev_value)

        # Template extraction
        template_id, template_str, template_params = self._parser.parse(message)

        # Entity extraction
        entities = self._extractor.extract(message)

        return SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=raw.received_ns,
            observed_ns=time.time_ns(),
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
