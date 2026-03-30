"""Integration tests for EventNormalizer — full pipeline with real components."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from seerflow.models.event import SeerflowEvent, SeverityLevel
from seerflow.parsing.drain import DrainParser
from seerflow.parsing.entities import EntityExtractor
from seerflow.parsing.normalizer import EventNormalizer
from seerflow.receivers.base import RawEvent


def _raw(msg: str, **meta: Any) -> RawEvent:
    return RawEvent(
        data=msg.encode(),
        source_type="syslog",
        source_id="integ",
        received_ns=1_710_000_000_000_000_000,
        metadata=dict(meta),
    )


class TestNormalizerEndToEnd:
    """Full pipeline: bytes → decode → DrainParser → EntityExtractor → SeerflowEvent."""

    def test_full_pipeline_produces_event(self) -> None:
        normalizer = EventNormalizer()
        result = normalizer.normalize(
            _raw("Login from 192.168.1.1 user=admin on host web-01.prod")
        )
        assert isinstance(result, SeerflowEvent)
        assert "192.168.1.1" in result.related_ips
        assert "admin" in result.related_users
        assert result.source_type == "syslog"

    def test_template_generalizes_across_events(self) -> None:
        normalizer = EventNormalizer()
        normalizer.normalize(_raw("Failed login from 10.0.0.1 user=alice"))
        r2 = normalizer.normalize(_raw("Failed login from 10.0.0.2 user=bob"))
        assert r2.template_id >= 1
        assert "<" in r2.template_str or "*" in r2.template_str  # wildcards

    def test_severity_propagated_from_metadata(self) -> None:
        normalizer = EventNormalizer()
        result = normalizer.normalize(_raw("kernel panic", seerflow_severity=5))
        assert result.severity_id == SeverityLevel.CRITICAL

    def test_injected_components_used(self) -> None:
        parser = DrainParser(sim_th=0.3, depth=3)
        extractor = EntityExtractor(enabled_types=frozenset({"ip"}))
        normalizer = EventNormalizer(drain_parser=parser, entity_extractor=extractor)
        result = normalizer.normalize(_raw("request from 10.0.0.1 user=root"))
        assert "10.0.0.1" in result.related_ips
        assert result.related_users == ()  # user extraction disabled

    def test_encoding_errors_produce_valid_event(self) -> None:
        raw = RawEvent(
            data=b"log \xff\xfe entry",
            source_type="file",
            source_id="test",
            received_ns=0,
            metadata={},
        )
        normalizer = EventNormalizer()
        result = normalizer.normalize(raw)
        assert isinstance(result, SeerflowEvent)
        assert "\ufffd" in result.message


class TestHandlerNormalizerIntegration:
    """Integration: handler + EventNormalizer + storage round-trip."""

    async def test_syslog_severity_propagates_to_storage(self, tmp_path: Path) -> None:
        """Syslog event with severity metadata -> handler -> storage -> correct severity_id."""
        from seerflow.config import SeerflowConfig, StorageConfig
        from seerflow.detection.ensemble import DetectionEnsemble
        from seerflow.models.query import EventQuery
        from seerflow.pipeline.handler import _make_handler
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)
        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        handler = _make_handler(ensemble, storage)

        event = RawEvent(
            data=b"kernel: segfault at 0000000000000000",
            source_type="syslog",
            source_id="test-syslog",
            received_ns=1_700_000_000_000_000_000,
            metadata={"seerflow_severity": SeverityLevel.CRITICAL.value},
        )
        await handler(event)

        # Flush WriteBuffer before querying
        assert storage._write_buffer is not None
        await storage._write_buffer.flush()

        result = await storage.query_events(EventQuery(limit=10))
        assert len(result.items) == 1
        assert result.items[0].severity_id == SeverityLevel.CRITICAL

        await storage.close()

    async def test_file_tail_defaults_to_informational(self, tmp_path: Path) -> None:
        """File tail event (no metadata) -> handler -> storage -> INFORMATIONAL."""
        from seerflow.config import SeerflowConfig, StorageConfig
        from seerflow.detection.ensemble import DetectionEnsemble
        from seerflow.models.query import EventQuery
        from seerflow.pipeline.handler import _make_handler
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)
        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        handler = _make_handler(ensemble, storage)

        event = RawEvent(
            data=b"plain log line from file tail",
            source_type="file",
            source_id="test-file",
            received_ns=1_700_000_000_000_000_000,
            metadata={},
        )
        await handler(event)

        assert storage._write_buffer is not None
        await storage._write_buffer.flush()

        result = await storage.query_events(EventQuery(limit=10))
        assert len(result.items) == 1
        assert result.items[0].severity_id == SeverityLevel.INFORMATIONAL

        await storage.close()

    async def test_entity_refs_round_trip_to_storage(self, tmp_path: Path) -> None:
        """Event with entities -> handler -> storage -> entity_refs persisted as UUID5."""
        import uuid

        from seerflow.config import SeerflowConfig, StorageConfig
        from seerflow.detection.ensemble import DetectionEnsemble
        from seerflow.models.entity import resolve_entities
        from seerflow.models.query import EventQuery
        from seerflow.pipeline.handler import _make_handler
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        storage = await SqliteBackend.connect(storage_cfg)
        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        handler = _make_handler(ensemble, storage)

        event = RawEvent(
            data=b"Failed login from 10.0.1.5 by user admin",
            source_type="syslog",
            source_id="test",
            received_ns=1_700_000_000_000_000_000,
            metadata={},
        )
        await handler(event)

        assert storage._write_buffer is not None
        await storage._write_buffer.flush()

        result = await storage.query_events(EventQuery(limit=10))
        assert len(result.items) == 1
        stored = result.items[0]
        assert "10.0.1.5" in stored.related_ips
        assert len(stored.entity_refs) > 0
        # entity_refs should contain UUID5 strings (not raw values)
        for ref in stored.entity_refs:
            parsed = uuid.UUID(ref)
            assert parsed.version == 5
        # entity_refs should match resolve_entities output for the same raw values
        expected = resolve_entities(stored.related_ips, stored.related_users, stored.related_hosts)
        assert stored.entity_refs == expected

        await storage.close()
