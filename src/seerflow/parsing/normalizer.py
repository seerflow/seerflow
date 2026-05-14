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
from seerflow.parsing._constants import MAX_MESSAGE_LEN, MAX_RAW_BYTES
from seerflow.parsing.drain import DrainParser
from seerflow.parsing.entities import EntityExtractor

if TYPE_CHECKING:
    from seerflow.receivers.base import RawEvent

_log = logging.getLogger(__name__)


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
        self._extractor = entity_extractor or EntityExtractor()

    @property
    def parser(self) -> DrainParser:
        """Public, read-only handle on the embedded Drain3 parser (S-081).

        The shutdown drain layer in ``pipeline.run`` persists template state to
        the model store via ``save_drain_state(parser, store)``; exposing the
        instance here avoids reaching into ``_parser`` from callers.
        """
        return self._parser

    def normalize(self, raw: RawEvent) -> SeerflowEvent:
        """Convert a RawEvent to a SeerflowEvent."""
        observed_ns = time.time_ns()

        data = raw.data
        if len(data) > MAX_RAW_BYTES:
            data = data[:MAX_RAW_BYTES]
        message = data.decode("utf-8", errors="replace")
        if len(message) > MAX_MESSAGE_LEN:
            message = message[:MAX_MESSAGE_LEN]

        # Severity from metadata (set by SyslogReceiver) or default
        sev_value = raw.metadata.get(
            "seerflow_severity",
            SeverityLevel.INFORMATIONAL.value,
        )
        try:
            severity = SeverityLevel(sev_value)
        except (ValueError, KeyError, TypeError):
            _log.warning(
                "Invalid seerflow_severity type=%s, defaulting to INFORMATIONAL",
                type(sev_value).__name__,
            )
            severity = SeverityLevel.INFORMATIONAL

        # Template extraction
        template_id, template_str, template_params = self._parser.parse(message)

        # Entity extraction (params-aware tagging).
        # Tags (param/template/unknown) are computed but only .value is stored
        # in the event. The correlation layer (S-034) will use the full tagged
        # representation for entity graph edge weighting.
        tagged = self._extractor.extract_tagged(message, params=template_params)

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
            related_ips=tuple(e.value for e in tagged.get("ip", [])),
            related_users=tuple(e.value for e in tagged.get("user", [])),
            related_hosts=tuple(e.value for e in tagged.get("host", [])),
            related_files=tuple(e.value for e in tagged.get("file", [])),
            related_domains=tuple(e.value for e in tagged.get("domain", [])),
            related_processes=tuple(e.value for e in tagged.get("process", [])),
        )
